"""Load a bronze parquet from S3 into the BigQuery bronze table.

BQ has no native S3 reader. CLAUDE.md gave us two options:
  (a) download the parquet locally and load via `load_table_from_file`, or
  (b) stage it in GCS first and `load_table_from_uri`.

We pick (a). The parquet is ~50 MB after snappy compression, the BQ upload
is a single HTTP POST, and (b) would require provisioning a GCS bucket just
to move a file we already have sitting in S3. If we ever need to load
hundreds of GB, we'll revisit.

Idempotency: a re-run of the same ``_ingestion_date`` deletes the existing
rows for that date before appending, so the day's partition always reflects
the latest successful load. Load job uses CREATE_IF_NEEDED + explicit
time-partitioning on ``_ingestion_date``, so the first-ever run provisions
the table with the right shape.
"""

from __future__ import annotations

import re
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import boto3
import structlog
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from src.config import get_settings

log = structlog.get_logger(__name__)

_BRONZE_TABLE_NAME = "ses_seguros"
_CLUSTER_FIELDS = ["coenti"]  # "entidade" code — most common filter
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


def _fq_table() -> str:
    s = get_settings()
    return f"{s.gcp_project_id}.{s.gcp_bq_dataset_bronze}.{_BRONZE_TABLE_NAME}"


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


def _load_parquet(client: bigquery.Client, parquet_path: Path, table_id: str) -> int:
    """Load a single parquet file into the bronze table. Returns rows loaded."""
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
        time_partitioning=bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="_ingestion_date",
        ),
        clustering_fields=_CLUSTER_FIELDS,
        # Parquet carries its own schema; let BQ honour it directly.
        autodetect=False,
    )
    log.info(
        "bq_loader.load.start",
        table=table_id,
        source=str(parquet_path),
        bytes=parquet_path.stat().st_size,
    )
    with parquet_path.open("rb") as fh:
        load_job = client.load_table_from_file(fh, table_id, job_config=job_config)
    load_job.result()
    rows = int(load_job.output_rows or 0)
    log.info("bq_loader.load.ok", table=table_id, rows_loaded=rows)
    return rows


def run_bronze_load(bronze_s3_uri: str) -> dict[str, Any]:
    """Download a bronze parquet from S3 and (re)load its partition into BQ."""
    settings = get_settings()
    if not settings.gcp_project_id:
        raise RuntimeError("GCP_PROJECT_ID not set — populate .env first.")

    bucket, key = _parse_s3_uri(bronze_s3_uri)
    ingestion_date = _extract_ingestion_date(key)
    table_id = _fq_table()

    client = bigquery.Client(project=settings.gcp_project_id)

    with tempfile.TemporaryDirectory(prefix="susep-bqload-") as tmpdir:
        local = Path(tmpdir) / "bronze.parquet"
        log.info("bq_loader.s3.download.start", uri=bronze_s3_uri)
        boto3.client("s3").download_file(bucket, key, str(local))
        log.info(
            "bq_loader.s3.download.ok",
            uri=bronze_s3_uri,
            bytes=local.stat().st_size,
        )

        deleted = _delete_existing_partition(client, table_id, ingestion_date)
        loaded = _load_parquet(client, local, table_id)

    return {
        "table": table_id,
        "bronze_s3_uri": bronze_s3_uri,
        "ingestion_date": ingestion_date.isoformat(),
        "rows_deleted": deleted,
        "rows_loaded": loaded,
    }


def main() -> int:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )
    if len(sys.argv) != 2:
        print(
            "Usage: python -m src.loaders.bq_loader "
            "s3://susep-ses-data/bronze/ses_seguros/ingestion_date=.../*.parquet",
            file=sys.stderr,
        )
        return 2
    try:
        result = run_bronze_load(sys.argv[1])
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("---")
    for k, v in result.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
