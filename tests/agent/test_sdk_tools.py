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
    get_search_log,
    reset_query_log,
    reset_search_log,
    run_sql_tool,
    search_news_tool,
)
from src.agent.tools.bq_query import QueryTooExpensiveError
from src.config import Settings


def test_allowed_tools_are_fully_qualified() -> None:
    assert ALLOWED_TOOLS == [
        f"mcp__{SERVER_NAME}__describe_table",
        f"mcp__{SERVER_NAME}__sample_rows",
        f"mcp__{SERVER_NAME}__run_sql",
        f"mcp__{SERVER_NAME}__read_report",
        f"mcp__{SERVER_NAME}__search_news",
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


def _call_search(query: str) -> dict[str, Any]:
    return asyncio.run(search_news_tool.handler({"query": query}))


def test_search_news_logs_and_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sdk_tools, "get_settings", lambda: Settings(tavily_api_key="k", news_max_searches=2)
    )
    monkeypatch.setattr(
        sdk_tools,
        "search_news",
        lambda query, **kw: [{"title": "t", "url": "u", "source": "s"}],
    )
    reset_search_log()

    out1 = _call_search("CAIXA parceria")
    payload = json.loads(out1["content"][0]["text"])
    assert payload["results"][0]["title"] == "t"
    assert payload["searches_remaining"] == 1

    _call_search("BBSE aquisição")
    out3 = _call_search("PORTO acordo")  # over the cap of 2

    assert out3.get("is_error") is True
    log = get_search_log()
    assert [(e.search_no, e.status) for e in log] == [
        (1, "ok"),
        (2, "ok"),
        (3, "rejected"),
    ]


def test_search_news_tool_contains_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sdk_tools, "get_settings", lambda: Settings(tavily_api_key="k", news_max_searches=5)
    )

    def boom(query: str, **kw: Any) -> list[dict[str, Any]]:
        raise RuntimeError("tavily down")

    monkeypatch.setattr(sdk_tools, "search_news", boom)
    reset_search_log()

    out = _call_search("x")
    assert out.get("is_error") is True
    (entry,) = get_search_log()
    assert entry.status == "error"
    assert "tavily down" in (entry.error or "")


def test_build_server_registers_news_tool_only_with_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_create(name: str, version: str, tools: list[Any]) -> str:
        captured["tools"] = [t.name for t in tools]
        return "server"

    monkeypatch.setattr(sdk_tools, "create_sdk_mcp_server", fake_create)

    monkeypatch.setattr(sdk_tools, "get_settings", lambda: Settings(tavily_api_key=""))
    build_bq_server()
    assert "search_news" not in captured["tools"]

    monkeypatch.setattr(sdk_tools, "get_settings", lambda: Settings(tavily_api_key="k"))
    build_bq_server()
    assert "search_news" in captured["tools"]


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
