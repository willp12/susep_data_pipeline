"""Expose the read-only BQ functions as in-process Claude Agent SDK tools.

The plain functions live in ``src.agent.tools`` (CP-B, fully unit-tested). Here
we wrap each as an ``@tool`` and bundle them into an SDK MCP server. Keeping the
wrapping this thin means the SDK layer has almost no logic to test — the cost
guardrails and serialisation already live (and are tested) underneath.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, Any

from claude_agent_sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
    create_sdk_mcp_server,
    tool,
)

from src.agent.history import read_report
from src.agent.tools import describe_table, run_sql, sample_rows, search_news
from src.agent.tools.bq_query import NonReadOnlyQueryError, QueryTooExpensiveError
from src.config import get_settings

SERVER_NAME = "bq"


@dataclass
class QueryLogEntry:
    """One run_sql call, as captured for the report's SQL appendix."""

    query_no: int
    sql: str
    status: str  # 'ok' | 'rejected' | 'error'
    bytes_processed: int | None = None
    row_count: int | None = None
    cache_hit: bool | None = None
    error: str | None = None


# Run-scoped registry of every run_sql call. The agent process drives exactly
# one run, and build_bq_server (called once per run) resets it.
_QUERY_LOG: list[QueryLogEntry] = []


def get_query_log() -> list[QueryLogEntry]:
    return list(_QUERY_LOG)


def reset_query_log() -> None:
    _QUERY_LOG.clear()


@dataclass
class SearchLogEntry:
    """One search_news call, captured for the run log / sources appendix."""

    search_no: int
    query: str
    status: str  # 'ok' | 'rejected' | 'error'
    results: list[dict[str, Any]] | None = None
    error: str | None = None


# Run-scoped, reset alongside the query log in build_bq_server.
_SEARCH_LOG: list[SearchLogEntry] = []


def get_search_log() -> list[SearchLogEntry]:
    return list(_SEARCH_LOG)


def reset_search_log() -> None:
    _SEARCH_LOG.clear()


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
    "only the columns you need. Returns rows + bytes processed + a `query_no` you "
    "must use to cite this query in the report.",
    {"sql": Annotated[str, "BigQuery Standard SQL query"]},
)
async def run_sql_tool(args: dict[str, Any]) -> dict[str, Any]:
    sql = str(args["sql"])
    entry = QueryLogEntry(query_no=len(_QUERY_LOG) + 1, sql=sql, status="error")
    _QUERY_LOG.append(entry)
    try:
        result = run_sql(sql)
    except (QueryTooExpensiveError, NonReadOnlyQueryError) as exc:
        entry.status = "rejected"
        entry.error = str(exc)
        return _error(str(exc))
    except Exception as exc:
        entry.error = f"run_sql failed: {exc}"
        return _error(entry.error)
    entry.status = "ok"
    entry.bytes_processed = result["bytes_processed"]
    entry.row_count = result["row_count"]
    entry.cache_hit = result["cache_hit"]
    return _ok({"query_no": entry.query_no, **result})


@tool(
    "read_report",
    "Read the full markdown of a previous report by date (YYYY-MM-DD, or "
    "YYYY-MM-DD_2 for same-day reruns). MANDATORY first step of a deep-dive "
    "run: call it on the report whose thread you are deepening — it returns "
    "the prior numbers and the SQL behind them.",
    {"date": Annotated[str, "Report stem, YYYY-MM-DD or YYYY-MM-DD_n"]},
)
async def read_report_tool(args: dict[str, Any]) -> dict[str, Any]:
    try:
        return _ok({"date": args["date"], "markdown": read_report(args["date"])})
    except Exception as exc:
        return _error(f"read_report failed: {exc}")


@tool(
    "search_news",
    "Search recent Brazil-focused web news about an insurer/group/market theme "
    "(partnerships, M&A, regulation, distribution deals) via Tavily. WRITE THE "
    "QUERY IN PORTUGUESE (e.g. 'CAIXA Seguridade parceria varejo'). Returns "
    "title, source, url, published date and snippet. News is CONTEXT — market "
    "figures still come only from BigQuery, and every news mention must cite "
    "source + date + url. Searches per run are capped.",
    {
        "query": Annotated[str, "Search query IN PORTUGUESE, e.g. 'BB Seguros parceria varejo'"],
        "days_back": Annotated[int, "Recency window in days (default 90)"],
        "max_results": Annotated[int, "Results to return, 1-10 (default 5)"],
    },
)
async def search_news_tool(args: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    query = str(args["query"])
    entry = SearchLogEntry(search_no=len(_SEARCH_LOG) + 1, query=query, status="error")

    used = sum(1 for e in _SEARCH_LOG if e.status == "ok")
    if used >= settings.news_max_searches:
        entry.status = "rejected"
        entry.error = f"search cap reached ({settings.news_max_searches}/run)"
        _SEARCH_LOG.append(entry)
        return _error(
            f"Search cap reached ({settings.news_max_searches} per run) — work "
            "with the results you already have."
        )
    _SEARCH_LOG.append(entry)

    try:
        results = search_news(
            query,
            days_back=int(args.get("days_back", 90)),
            max_results=int(args.get("max_results", 5)),
        )
    except Exception as exc:
        entry.error = f"search_news failed: {exc}"
        return _error(entry.error)
    entry.status = "ok"
    entry.results = results
    remaining = settings.news_max_searches - used - 1
    return _ok({"results": results, "searches_remaining": remaining})


_TOOLS = [describe_table_tool, sample_rows_tool, run_sql_tool, read_report_tool]
_NEWS_TOOLS = [search_news_tool]

# The gate allows the name even when the tool isn't registered (no key) — a
# non-registered tool simply doesn't exist for the model, so this is safe.
ALLOWED_TOOLS = [f"mcp__{SERVER_NAME}__{t.name}" for t in (*_TOOLS, *_NEWS_TOOLS)]


async def tool_gate(
    tool_name: str,
    tool_input: dict[str, Any],
    context: ToolPermissionContext,
) -> PermissionResultAllow | PermissionResultDeny:
    """Default-deny: only the registered BQ tools may run."""
    if tool_name in ALLOWED_TOOLS:
        return PermissionResultAllow()
    return PermissionResultDeny(
        message=f"Tool '{tool_name}' is not allowed. Use only the bq tools.",
    )


def build_bq_server() -> Any:
    """Build the in-process MCP server with the tools available for this run.

    search_news is only registered when TAVILY_API_KEY is configured, so the
    model never sees a tool it can't use. Also resets the query/search logs:
    one server build == one agent run.
    """
    reset_query_log()
    reset_search_log()
    tools = list(_TOOLS)
    if get_settings().tavily_api_key:
        tools.extend(_NEWS_TOOLS)
    return create_sdk_mcp_server(name=SERVER_NAME, version="0.1.0", tools=tools)
