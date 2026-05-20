"""describe_table — return a table's schema + metadata, no query, no cost.

Uses ``Client.get_table`` (a metadata GET), so the agent can learn the shape
of a table and read column descriptions (sourced from dbt docs in CP-C)
without spending any BigQuery bytes.
"""

from __future__ import annotations

from typing import Any

import structlog
from google.cloud import bigquery

from src.agent.tools._client import get_client
from src.config import get_settings

log = structlog.get_logger(__name__)


def _resolve_table_id(dataset: str, table: str) -> str:
    project = get_settings().gcp_project_id
    return f"{project}.{dataset}.{table}"


def describe_table(
    dataset: str,
    table: str,
    *,
    client: bigquery.Client | None = None,
) -> dict[str, Any]:
    """Describe one BigQuery table.

    Returns columns (name/type/mode/description), partitioning, clustering,
    row/byte counts and the table description.
    """
    client = client or get_client()
    table_id = _resolve_table_id(dataset, table)
    tbl = client.get_table(table_id)

    columns = [
        {
            "name": field.name,
            "type": field.field_type,
            "mode": field.mode,
            "description": field.description,
        }
        for field in tbl.schema
    ]

    partitioning: dict[str, Any] | None = None
    if tbl.time_partitioning is not None:
        partitioning = {
            "type": tbl.time_partitioning.type_,
            "field": tbl.time_partitioning.field,
        }

    result = {
        "table_id": table_id,
        "num_rows": tbl.num_rows,
        "num_bytes": tbl.num_bytes,
        "columns": columns,
        "partitioning": partitioning,
        "clustering_fields": tbl.clustering_fields,
        "description": tbl.description,
    }
    log.info(
        "agent.tool.describe_table",
        table=table_id,
        num_columns=len(columns),
        num_rows=tbl.num_rows,
    )
    return result
