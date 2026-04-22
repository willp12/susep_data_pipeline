"""Load a bronze parquet from S3 into the corresponding BigQuery bronze table.

BQ has no native S3 reader. CLAUDE.md gave us two options:
  (a) download the parquet locally and load via `load_table_from_file`, or
  (b) stage it in GCS first and `load_table_from_uri`.

We pick (a). Bronze parquets are tens of MB after snappy, the BQ upload is a
single HTTP POST, and (b) would require provisioning a GCS bucket just to
move a file we already have in S3. If we ever need to load hundreds of GB,
we'll revisit.

Load strategy is dispatched on ``spec.load_mode``:

- ``append_partition`` — fact-style monthly dumps (e.g. ``ses_seguros``).
  Day-partitioned on ``_ingestion_date``; idempotent by deleting the target
  partition before a WRITE_APPEND. Respects ``spec.cluster_by``.
- ``truncate_replace`` — reference/dimension data (ramos, grupos, cias).
  WRITE_TRUNCATE per run. No partitioning, no clustering. ``_ingestion_date``
  still stamped as a regular column by bronze for provenance.

The ``match`` in :func:`run_bronze_load` uses ``assert_never`` on the default
arm so mypy refuses to compile a third ``LoadMode`` value without explicit
dispatch. That's the whole point — if someone adds ``load_mode="stream"`` to
the registry, they get a type error here, not a silent fallthrough.
"""

from __future__ import annotations

import re
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, assert_never

import boto3
import structlog
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from src.config import get_settings
from src.csv_registry import CsvSpec, get_spec

log = structlog.get_logger(__name__)

_KEY_DATE_RE = re.compile(r"ingestion_date=(\d{4}-\d{2}-\d{2})")


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"Not an s3:// URI: {uri}")
    bucket, _, key = uri[len("s3://") :].partition("/")
    if not bucket or not key:
        raise ValueError(f"Malformed s3:// URI: {uri}")
    return bucket, key


def _extract_ingestion_date(key: str) -> date:
    """Parse ``ingestion_date=YYYY-MM-DD`` out of the S3 key."""
    m = _KEY_DATE_RE.search(key)
    if m is None:
        raise ValueError(f"Key does not contain 'ingestion_date=YYYY-MM-DD': {key}")
    return date.fromisoformat(m.group(1))


def _fq_table(table_name: str) -> str:
    s = get_settings()
    return f"{s.gcp_project_id}.{s.gcp_bq_dataset_bronze}.{table_name}"


def _delete_existing_partition(client: bigquery.Client, table_id: str, ingestion_date: date) -> int:
    """Remove any existing rows for ``ingestion_date``. Returns rows deleted."""
    try:
        client.get_table(table_id)
    except NotFound:
        log.info("bq_loader.delete.skip_no_table", table=table_id)
        return 0

    query = f"""
        DELETE FROM `{table_id}`
        WHERE _ingestion_date = @d
    """  # noqa: S608 -- table id from validated settings, not user input
    job = client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("d", "DATE", ingestion_date),
            ]
        ),
    )
    job.result()
    affected = int(job.num_dml_affected_rows or 0)
    log.info(
        "bq_loader.delete.ok",
        table=table_id,
        ingestion_date=ingestion_date.isoformat(),
        rows_deleted=affected,
    )
    return affected


def _run_load_job(
    client: bigquery.Client,
    parquet_path: Path,
    table_id: str,
    job_config: bigquery.LoadJobConfig,
) -> int:
    """Execute a BQ load job from a local parquet. Returns rows loaded."""
    log.info(
        "bq_loader.load.start",
        table=table_id,
        source=str(parquet_path),
        bytes=parquet_path.stat().st_size,
        write_disposition=job_config.write_disposition,
    )
    with parquet_path.open("rb") as fh:
        load_job = client.load_table_from_file(fh, table_id, job_config=job_config)
    load_job.result()
    rows = int(load_job.output_rows or 0)
    log.info("bq_loader.load.ok", table=table_id, rows_loaded=rows)
    return rows


def _load_append_partition(
    spec: CsvSpec,
    client: bigquery.Client,
    parquet_path: Path,
    table_id: str,
    ingestion_date: date,
) -> dict[str, Any]:
    """Day-partitioned append: DELETE today's rows, then WRITE_APPEND."""
    deleted = _delete_existing_partition(client, table_id, ingestion_date)
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
        time_partitioning=bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="_ingestion_date",
        ),
        clustering_fields=list(spec.cluster_by) if spec.cluster_by else None,
        # Parquet carries its own schema; let BQ honour it directly.
        autodetect=False,
        # Allow the table to gain columns between runs without a manual
        # migration. Two real cases this unblocks: the one-time addition of
        # ``_extras`` (Fase 2 schema contract), and any future expansion of
        # ``spec.expected_columns`` when SUSEP ships a new field. The flag
        # only ALLOWS additions — it doesn't fabricate anything, so a plain
        # same-schema run is unaffected.
        schema_update_options=[
            bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION,
        ],
    )
    rows = _run_load_job(client, parquet_path, table_id, job_config)
    return {
        "load_mode": spec.load_mode,
        "ingestion_date": ingestion_date.isoformat(),
        "rows_deleted": deleted,
        "rows_loaded": rows,
    }


def _load_truncate_replace(
    spec: CsvSpec,
    client: bigquery.Client,
    parquet_path: Path,
    table_id: str,
) -> dict[str, Any]:
    """Wholesale replace: WRITE_TRUNCATE, no partitioning, no clustering.

    Reference tables (ramos, grupos, cias) are small and replace-in-full each
    run. Partitioning would just add overhead without buying idempotency —
    truncation is already idempotent by definition.
    """
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
        autodetect=False,
    )
    rows = _run_load_job(client, parquet_path, table_id, job_config)
    return {
        "load_mode": spec.load_mode,
        "rows_loaded": rows,
    }


def run_bronze_load(bronze_s3_uri: str, spec: CsvSpec) -> dict[str, Any]:
    """Download a bronze parquet from S3 and load it per ``spec.load_mode``."""
    settings = get_settings()
    if not settings.gcp_project_id:
        raise RuntimeError("GCP_PROJECT_ID not set — populate .env first.")

    bucket, key = _parse_s3_uri(bronze_s3_uri)
    table_id = _fq_table(spec.table_name)
    client = bigquery.Client(project=settings.gcp_project_id)

    with tempfile.TemporaryDirectory(prefix=f"susep-bqload-{spec.table_name}-") as tmpdir:
        local = Path(tmpdir) / "bronze.parquet"
        log.info("bq_loader.s3.download.start", uri=bronze_s3_uri)
        boto3.client("s3").download_file(bucket, key, str(local))
        log.info(
            "bq_loader.s3.download.ok",
            uri=bronze_s3_uri,
            bytes=local.stat().st_size,
        )

        match spec.load_mode:
            case "append_partition":
                ingestion_date = _extract_ingestion_date(key)
                details = _load_append_partition(spec, client, local, table_id, ingestion_date)
            case "truncate_replace":
                details = _load_truncate_replace(spec, client, local, table_id)
            case _:
                assert_never(spec.load_mode)

    return {
        "spec": spec.table_name,
        "table": table_id,
        "bronze_s3_uri": bronze_s3_uri,
        **details,
    }


def main() -> int:
    """CLI smoke test: ``python -m src.loaders.bq_loader <s3_uri> <table>``."""
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )
    if len(sys.argv) != 3:
        print(
            "Usage: python -m src.loaders.bq_loader <bronze_s3_uri> <table_name>",
            file=sys.stderr,
        )
        return 2
    try:
        spec = get_spec(sys.argv[2])
        result = run_bronze_load(sys.argv[1], spec)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("---")
    for k, v in result.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
