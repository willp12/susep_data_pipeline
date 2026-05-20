"""run_sql — execute arbitrary read-only SQL with a hard bytes cap.

Cost safety has two layers:
  1. A mandatory dry-run estimates ``total_bytes_processed`` before running.
     If it exceeds ``max_bytes`` we raise ``QueryTooExpensiveError`` and never run
     the real job.
  2. The real job sets ``maximum_bytes_billed`` so BigQuery itself aborts if
     the estimate was somehow wrong (belt and suspenders).

We do not sanitise the SQL: the agent's service account is read-only
(``bigquery.dataViewer`` + ``bigquery.jobUser``), so IAM is the trust
boundary, not string parsing.
"""

from __future__ import annotations

from typing import Any

import structlog
from google.cloud import bigquery

from src.agent.tools._client import get_client
from src.agent.tools._serde import jsonable_row

log = structlog.get_logger(__name__)

_GIB = 1024**3
DEFAULT_MAX_BYTES = 1 * _GIB


class QueryTooExpensiveError(RuntimeError):
    """Raised when the dry-run estimate exceeds the byte cap."""

    def __init__(self, estimated_bytes: int, max_bytes: int) -> None:
        self.estimated_bytes = estimated_bytes
        self.max_bytes = max_bytes
        super().__init__(
            f"Query would process {estimated_bytes / _GIB:.3f} GiB, over the "
            f"{max_bytes / _GIB:.3f} GiB cap. Narrow the scan — add a partition "
            "filter on _ingestion_date or select fewer columns."
        )


def _dry_run_bytes(client: bigquery.Client, sql: str) -> int:
    cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    job = client.query(sql, job_config=cfg)
    return int(job.total_bytes_processed or 0)


def run_sql(
    sql: str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    client: bigquery.Client | None = None,
) -> dict[str, Any]:
    """Run read-only SQL, capped at ``max_bytes`` of data scanned.

    Raises ``QueryTooExpensiveError`` (before executing) if the dry-run estimate is
    over the cap.
    """
    client = client or get_client()

    estimated = _dry_run_bytes(client, sql)
    if estimated > max_bytes:
        log.warning(
            "agent.tool.run_sql.rejected",
            bytes_estimated=estimated,
            max_bytes=max_bytes,
        )
        raise QueryTooExpensiveError(estimated, max_bytes)

    cfg = bigquery.QueryJobConfig(maximum_bytes_billed=max_bytes)
    job = client.query(sql, job_config=cfg)
    rows = [jsonable_row(row) for row in job.result()]

    result = {
        "rows": rows,
        "row_count": len(rows),
        "bytes_estimated": estimated,
        "bytes_processed": int(job.total_bytes_processed or 0),
        "cache_hit": bool(job.cache_hit),
        "job_id": job.job_id,
    }
    log.info(
        "agent.tool.run_sql.ok",
        row_count=len(rows),
        bytes_processed=result["bytes_processed"],
        cache_hit=result["cache_hit"],
    )
    return result
