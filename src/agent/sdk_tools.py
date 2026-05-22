"""Expose the read-only BQ functions as in-process Claude Agent SDK tools.

The plain functions live in ``src.agent.tools`` (CP-B, fully unit-tested). Here
we wrap each as an ``@tool`` and bundle them into an SDK MCP server. Keeping the
wrapping this thin means the SDK layer has almost no logic to test — the cost
guardrails and serialisation already live (and are tested) underneath.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from src.agent.history import read_report
from src.agent.tools import describe_table, run_sql, sample_rows
from src.agent.tools.bq_query import QueryTooExpensiveError

SERVER_NAME = "bq"


def _ok(payload: Any) -> dict[str, Any]:
    text = json.dumps(payload, default=str, ensure_ascii=False)
    return {"content": [{"type": "text", "text": text}]}


def _error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "is_error": True}


@tool(
    "describe_table",
    "Schema + metadata of a BigQuery table (no query, no cost). "
    "Use it to discover columns, types and row counts.",
    {
        "dataset": Annotated[str, "Dataset, e.g. susep_ses_staging"],
        "table": Annotated[str, "Table name, e.g. stg_ses_seguros"],
    },
)
async def describe_table_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return _ok(describe_table(args["dataset"], args["table"]))
    except Exception as exc:
        return _error(f"describe_table failed: {exc}")


@tool(
    "sample_rows",
    "Up to N sample rows from a table (free, uses tabledata.list, no scan). 1 <= n <= 100.",
    {
        "dataset": Annotated[str, "Dataset"],
        "table": Annotated[str, "Table name"],
        "n": Annotated[int, "Number of rows, 1-100"],
    },
)
async def sample_rows_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return _ok(sample_rows(args["dataset"], args["table"], int(args.get("n", 5))))
    except Exception as exc:
        return _error(f"sample_rows failed: {exc}")


@tool(
    "run_sql",
    "Run read-only BigQuery Standard SQL. A mandatory dry-run rejects queries over "
    "the byte cap (~1 GiB) — always filter by the latest _ingestion_date and select "
    "only the columns you need. Returns rows + bytes processed.",
    {"sql": Annotated[str, "BigQuery Standard SQL query"]},
)
async def run_sql_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return _ok(run_sql(args["sql"]))
    except QueryTooExpensiveError as exc:
        return _error(str(exc))
    except Exception as exc:
        return _error(f"run_sql failed: {exc}")


@tool(
    "read_report",
    "Read the full markdown of a previous daily report by date (YYYY-MM-DD). "
    "Use it to deep-dive a thread the history digest mentions — it returns the "
    "prior numbers and the SQL behind them.",
    {"date": Annotated[str, "Report date, YYYY-MM-DD"]},
)
async def read_report_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return _ok({"date": args["date"], "markdown": read_report(args["date"])})
    except Exception as exc:
        return _error(f"read_report failed: {exc}")


_TOOLS = [describe_table_tool, sample_rows_tool, run_sql_tool, read_report_tool]

ALLOWED_TOOLS = [f"mcp__{SERVER_NAME}__{t.name}" for t in _TOOLS]


def build_bq_server() -> Any:
    """Build the in-process MCP server exposing the three BQ tools."""
    return create_sdk_mcp_server(name=SERVER_NAME, version="0.1.0", tools=_TOOLS)
