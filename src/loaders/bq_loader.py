"""Load a bronze parquet from GCS into the BigQuery bronze table.

Now that raw + bronze live in GCS (single-cloud), BigQuery loads the parquet
**natively** from ``gs://`` via ``load_table_from_uri`` — no local download, no
HTTP upload. (Under S3 we had to download then ``load_table_from_file``; the
GCS move removed that round-trip.)

Idempotency: a re-run of the same ``_ingestion_date`` deletes the existing
rows for that date before appending, so the day's partition always reflects
the latest successful load. Load job uses CREATE_IF_NEEDED + explicit
time-partitioning on ``_ingestion_date``, so the first-ever run provisions
the table with the right shape.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from typing import Any

import structlog
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from src.config import get_settings
from src.storage import gcs

log = structlog.get_logger(__name__)

_BRONZE_TABLE_NAME = "ses_seguros"
_CLUSTER_FIELDS = ["coenti"]  # "entidade" code — most common filter
_KEY_DATE_RE = re.compile(r"ingestion_date=(\d{4}-\d{2}-\d{2})")


def _extract_ingestion_date(key: str) -> date:
    """Parse ``ingestion_date=YYYY-MM-DD`` out of the GCS object key."""
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


def _load_parquet(client: bigquery.Client, gcs_uri: str, table_id: str) -> int:
    """Load a parquet straight from gs:// into the bronze table. Returns rows."""
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
    log.info("bq_loader.load.start", table=table_id, source=gcs_uri)
    load_job = client.load_table_from_uri(gcs_uri, table_id, job_config=job_config)
    load_job.result()
    rows = int(load_job.output_rows or 0)
    log.info("bq_loader.load.ok", table=table_id, rows_loaded=rows)
    return rows


def run_bronze_load(bronze_gcs_uri: str) -> dict[str, Any]:
    """(Re)load a bronze parquet's partition into BQ, straight from gs://."""
    settings = get_settings()
    if not settings.gcp_project_id:
        raise RuntimeError("GCP_PROJECT_ID not set — populate .env first.")

    _, key = gcs.parse_gcs_uri(bronze_gcs_uri)
    ingestion_date = _extract_ingestion_date(key)
    table_id = _fq_table()

    client = bigquery.Client(project=settings.gcp_project_id)
    deleted = _delete_existing_partition(client, table_id, ingestion_date)
    loaded = _load_parquet(client, bronze_gcs_uri, table_id)

    return {
        "table": table_id,
        "bronze_gcs_uri": bronze_gcs_uri,
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
            "gs://<project>-susep-ses-data/bronze/ses_seguros/ingestion_date=.../*.parquet",
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
