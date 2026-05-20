"""sample_rows — preview a handful of rows, free of charge.

Uses the tabledata.list REST endpoint (``Client.list_rows``) rather than a
``SELECT * LIMIT n`` query. list_rows reads straight from storage: no query
job, no bytes billed, no scan of the full partition set.
"""

from __future__ import annotations

from typing import Any

import structlog
from google.cloud import bigquery

from src.agent.tools._client import get_client
from src.agent.tools._serde import jsonable_row
from src.config import get_settings

log = structlog.get_logger(__name__)

_MAX_N = 100


def sample_rows(
    dataset: str,
    table: str,
    n: int = 5,
    *,
    client: bigquery.Client | None = None,
) -> dict[str, Any]:
    """Return up to ``n`` rows from a table (1 ≤ n ≤ 100), at zero query cost."""
    if not 1 <= n <= _MAX_N:
        raise ValueError(f"n must be between 1 and {_MAX_N}, got {n}")

    client = client or get_client()
    project = get_settings().gcp_project_id
    table_id = f"{project}.{dataset}.{table}"

    rows = [jsonable_row(row) for row in client.list_rows(table_id, max_results=n)]

    log.info("agent.tool.sample_rows", table=table_id, row_count=len(rows))
    return {
        "table_id": table_id,
        "rows": rows,
        "row_count": len(rows),
    }
