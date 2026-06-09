import asyncio
import json
from typing import Any

import pytest

import src.agent.sdk_tools as sdk_tools
from src.agent.sdk_tools import (
    ALLOWED_TOOLS,
    SERVER_NAME,
    build_bq_server,
    get_query_log,
    reset_query_log,
    run_sql_tool,
)
from src.agent.tools.bq_query import QueryTooExpensiveError


def test_allowed_tools_are_fully_qualified() -> None:
    assert ALLOWED_TOOLS == [
        f"mcp__{SERVER_NAME}__describe_table",
        f"mcp__{SERVER_NAME}__sample_rows",
        f"mcp__{SERVER_NAME}__run_sql",
        f"mcp__{SERVER_NAME}__read_report",
    ]


def test_build_bq_server_returns_config() -> None:
    server = build_bq_server()
    assert server is not None


def _call_run_sql(sql: str) -> dict[str, Any]:
    return asyncio.run(run_sql_tool.handler({"sql": sql}))


def test_run_sql_logs_queries_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_sql(sql: str) -> dict[str, Any]:
        return {
            "rows": [],
            "row_count": 0,
            "bytes_estimated": 10,
            "bytes_processed": 10,
            "cache_hit": False,
            "job_id": "j1",
        }

    monkeypatch.setattr(sdk_tools, "run_sql", fake_run_sql)
    reset_query_log()

    out1 = _call_run_sql("SELECT 1")
    out2 = _call_run_sql("SELECT 2")

    log = get_query_log()
    assert [(e.query_no, e.sql, e.status) for e in log] == [
        (1, "SELECT 1", "ok"),
        (2, "SELECT 2", "ok"),
    ]
    # query_no is surfaced to the model so it can cite the query.
    assert json.loads(out1["content"][0]["text"])["query_no"] == 1
    assert json.loads(out2["content"][0]["text"])["query_no"] == 2


def test_run_sql_logs_rejected_query(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_sql(sql: str) -> dict[str, Any]:
        raise QueryTooExpensiveError(2 * 1024**3, 1024**3)

    monkeypatch.setattr(sdk_tools, "run_sql", fake_run_sql)
    reset_query_log()

    out = _call_run_sql("SELECT * FROM huge")

    assert out.get("is_error") is True
    (entry,) = get_query_log()
    assert entry.status == "rejected"
    assert entry.error is not None


def test_build_bq_server_resets_query_log(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run_sql(sql: str) -> dict[str, Any]:
        return {
            "rows": [],
            "row_count": 0,
            "bytes_estimated": 1,
            "bytes_processed": 1,
            "cache_hit": True,
            "job_id": "j",
        }

    monkeypatch.setattr(sdk_tools, "run_sql", fake_run_sql)
    reset_query_log()
    _call_run_sql("SELECT 1")
    assert len(get_query_log()) == 1

    build_bq_server()
    assert get_query_log() == []
