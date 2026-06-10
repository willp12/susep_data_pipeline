from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from src.chat.session import build_chat_system_prompt, events_from_message
from tests.agent._fakes import FakeStore


def _seed(store: FakeStore) -> None:
    store.save_manifest(
        {
            "reports": [
                {
                    "stem": "2026-05-23",
                    "report_path": "reports/2026/2026-05-23.md",
                    "queries_path": None,
                    "titles": ["1. Crise em Marítimos Cascos"],
                }
            ]
        }
    )


def test_system_prompt_injects_history_and_glossary() -> None:
    store = FakeStore()
    _seed(store)
    prompt = build_chat_system_prompt(store)
    # Base conversational contract is present...
    assert "interactive" in prompt
    # ...plus the manifest digest and a glossary section (fallback or real).
    assert "Crise em Marítimos Cascos" in prompt
    assert "## Glossário (dbt docs)" in prompt


def test_events_from_assistant_message() -> None:
    message = AssistantMessage(
        content=[
            TextBlock(text="Olhando o report de 2026-05-23..."),
            ToolUseBlock(
                id="t1",
                name="mcp__bq__read_report",
                input={"date": "2026-05-23"},
            ),
            ToolUseBlock(
                id="t2",
                name="mcp__bq__run_sql",
                input={"sql": "SELECT   branch_name,\n  SUM(premio_direto)\nFROM x"},
            ),
        ],
        model="qwen/qwen3-14b",
    )
    events = events_from_message(message)
    assert [e.kind for e in events] == ["text", "tool", "tool"]
    assert events[1].text == "read_report: 2026-05-23"
    # SQL is whitespace-collapsed for display.
    assert events[2].text.startswith("run_sql: SELECT branch_name, SUM(premio_direto)")


def test_events_from_result_message() -> None:
    message = ResultMessage(
        subtype="success",
        duration_ms=1200,
        duration_api_ms=1100,
        is_error=False,
        num_turns=4,
        session_id="s1",
        total_cost_usd=0.123,
    )
    (event,) = events_from_message(message)
    assert event.kind == "result"
    assert event.data is not None
    assert event.data["cost_usd"] == 0.123
    assert event.data["num_turns"] == 4


def test_events_ignore_unknown_messages() -> None:
    assert events_from_message(object()) == []
