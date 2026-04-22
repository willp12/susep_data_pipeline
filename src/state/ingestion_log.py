"""BigQuery-backed ingestion log.

Owns two operations:

- ``get_latest_hash(file_name)`` — return the SHA256 of the most recent
  successful ingestion for a given logical file, or ``None`` if we've never
  ingested it. Used to short-circuit re-downloads when SUSEP hasn't refreshed
  the zip since our last run.
- ``insert_entry(...)`` — append one row describing the outcome of a run
  ('ingested' | 'no_change' | 'failed').

The schema matches ``scripts/bootstrap/03_gcp_bigquery.sh`` — partitioned by
``ingestion_date`` (DATE) and clustered by ``file_name`` (STRING).

DML is used on purpose instead of ``tabledata.insertAll`` (streaming insert):
DML writes are immediately visible to subsequent queries, so back-to-back
pipeline runs don't accidentally re-ingest a hash that's still sitting in a
streaming buffer. Volumes are tiny (one row per run) so the cost is nil.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Literal

import structlog
from google.cloud import bigquery

from src.config import get_settings

log = structlog.get_logger(__name__)

Status = Literal["ingested", "no_change", "failed"]

_TABLE_NAME = "ingestion_log"


def _fq_table() -> str:
    """Return ``project.dataset.ingestion_log`` from current settings."""
    s = get_settings()
    return f"{s.gcp_project_id}.{s.gcp_bq_dataset_bronze}.{_TABLE_NAME}"


@lru_cache(maxsize=1)
def _client() -> bigquery.Client:
    return bigquery.Client(project=get_settings().gcp_project_id)


def get_latest_hash(file_name: str) -> str | None:
    """Return the SHA256 of the most recent successful ingestion of ``file_name``.

    Only ``status = 'ingested'`` rows count — 'no_change' and 'failed' runs are
    ignored because their ``file_hash`` either repeats a prior ingest or isn't
    authoritative. Returns ``None`` if the file has never been ingested.
    """
    table = _fq_table()
    # Table identifier comes from validated settings, not user input.
    query = f"""
        SELECT file_hash
        FROM `{table}`
        WHERE file_name = @file_name
          AND status = 'ingested'
        ORDER BY run_timestamp DESC
        LIMIT 1
    """  # noqa: S608 -- table ref from validated settings, not user input
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("file_name", "STRING", file_name),
        ]
    )
    rows = _client().query(query, job_config=job_config).result()
    for row in rows:
        return str(row.file_hash)
    return None


def insert_entry(
    *,
    file_name: str,
    file_hash: str,
    source_url: str,
    status: Status,
    ingestion_date: date | None = None,
    run_timestamp: datetime | None = None,
) -> None:
    """Insert one row into the ingestion_log table.

    ``ingestion_date`` and ``run_timestamp`` default to UTC now/today so callers
    usually only need to pass the four business fields.
    """
    if run_timestamp is None:
        run_timestamp = datetime.now(UTC)
    if ingestion_date is None:
        ingestion_date = run_timestamp.date()

    table = _fq_table()
    query = f"""
        INSERT INTO `{table}` (
            ingestion_date, file_name, file_hash, source_url, status, run_timestamp
        )
        VALUES (
            @ingestion_date, @file_name, @file_hash, @source_url, @status, @run_timestamp
        )
    """  # noqa: S608 -- table ref from validated settings, not user input
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("ingestion_date", "DATE", ingestion_date),
            bigquery.ScalarQueryParameter("file_name", "STRING", file_name),
            bigquery.ScalarQueryParameter("file_hash", "STRING", file_hash),
            bigquery.ScalarQueryParameter("source_url", "STRING", source_url),
            bigquery.ScalarQueryParameter("status", "STRING", status),
            bigquery.ScalarQueryParameter("run_timestamp", "TIMESTAMP", run_timestamp),
        ]
    )
    _client().query(query, job_config=job_config).result()

    log.info(
        "ingestion_log.insert.ok",
        file_name=file_name,
        file_hash_prefix=file_hash[:12],
        status=status,
        ingestion_date=ingestion_date.isoformat(),
    )
