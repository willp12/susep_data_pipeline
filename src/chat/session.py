"""Multi-turn analyst chat over the published reports and BigQuery.

Wraps ``ClaudeSDKClient`` (the Agent SDK's interactive client — unlike the
one-shot ``query()`` the weekly agent uses, it keeps the session alive across
questions, so follow-ups see the whole conversation and prior tool results).
Reuses the agent's stack wholesale: the BQ/read_report tools and default-deny
gate from ``sdk_tools``, the manifest history digest, the dbt glossary and the
anthropic/local provider toggle.

The UI layer (CLI and Streamlit) consumes ``ask()`` as a stream of
``ChatEvent``s: assistant text, tool-call notices, and the per-question result
(cost). Keeping this module UI-agnostic is what lets the interface change
without touching the agent wiring.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from src.agent.glossary import build_glossary
from src.agent.history import build_history_digest
from src.agent.providers import provider_env, require_provider_credentials
from src.agent.publisher import ReportStore
from src.agent.sdk_tools import ALLOWED_TOOLS, SERVER_NAME, build_bq_server, tool_gate
from src.config import Settings, get_settings

log = structlog.get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "chat.md"


@dataclass
class ChatEvent:
    """One streamed unit of the assistant's answer.

    kind 'text'   — a chunk of assistant prose (``text``).
    kind 'tool'   — a tool call notice (``text`` is a short human label).
    kind 'result' — end of the answer; ``data`` carries cost/turn metadata.
    """

    kind: str
    text: str = ""
    data: dict[str, Any] | None = None


def _tool_label(block: ToolUseBlock) -> str:
    """Short human-readable label for a tool call, for UI display."""
    name = block.name.rsplit("__", 1)[-1]
    args = block.input or {}
    if name == "run_sql":
        sql = " ".join(str(args.get("sql", "")).split())
        return f"run_sql: {sql[:120]}{'…' if len(sql) > 120 else ''}"
    if name == "read_report":
        return f"read_report: {args.get('date', '?')}"
    if name in {"describe_table", "sample_rows"}:
        return f"{name}: {args.get('dataset', '?')}.{args.get('table', '?')}"
    return name


def events_from_message(message: Any) -> list[ChatEvent]:
    """Translate one SDK message into UI events (pure, unit-testable)."""
    events: list[ChatEvent] = []
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock) and block.text.strip():
                events.append(ChatEvent(kind="text", text=block.text))
            elif isinstance(block, ToolUseBlock):
                events.append(ChatEvent(kind="tool", text=_tool_label(block)))
    elif isinstance(message, ResultMessage):
        events.append(
            ChatEvent(
                kind="result",
                data={
                    "cost_usd": message.total_cost_usd,
                    "num_turns": message.num_turns,
                    "is_error": message.is_error,
                },
            )
        )
    return events


def build_chat_system_prompt(store: ReportStore) -> str:
    base = _PROMPT_PATH.read_text(encoding="utf-8")
    glossary = build_glossary()
    history = build_history_digest(store=store)
    return (
        f"{base}\n\n"
        f"## Glossário (dbt docs)\n\n{glossary}\n\n"
        f"## Histórico de reports (datas e temas já cobertos)\n\n{history}\n"
    )


class ChatSession:
    """One interactive conversation. Use as an async context manager."""

    def __init__(
        self,
        *,
        store: ReportStore | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        require_provider_credentials(self._settings)
        store = store or ReportStore()

        options = ClaudeAgentOptions(
            model=self._settings.agent_model,
            system_prompt=build_chat_system_prompt(store),
            mcp_servers={SERVER_NAME: build_bq_server()},
            allowed_tools=ALLOWED_TOOLS,
            can_use_tool=tool_gate,
            permission_mode="default",
            max_turns=self._settings.chat_max_turns,
            # Local runs cost nothing and report no usage; for the API the cap
            # covers the WHOLE conversation, not one question.
            max_budget_usd=(
                self._settings.chat_max_budget_usd
                if self._settings.agent_provider == "anthropic"
                else None
            ),
            env=provider_env(self._settings),
            cwd=str(_REPO_ROOT),
            # Don't inherit the repo's CLAUDE.md / settings into the session.
            setting_sources=None,
        )
        self._client = ClaudeSDKClient(options)
        self.total_cost_usd = 0.0
        self.provider = self._settings.agent_provider
        self.model = self._settings.agent_model

    async def __aenter__(self) -> ChatSession:
        await self._client.connect()
        log.info("chat.session.start", model=self.model, provider=self.provider)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._client.disconnect()
        log.info("chat.session.end", total_cost_usd=self.total_cost_usd)

    async def ask(self, prompt: str) -> AsyncIterator[ChatEvent]:
        """Send one user question; yield events until the answer completes."""
        await self._client.query(prompt)
        async for message in self._client.receive_response():
            for event in events_from_message(message):
                if event.kind == "result" and event.data and event.data.get("cost_usd"):
                    # The CLI reports total_cost_usd cumulatively for the
                    # session, so this is an assignment, not an accumulation.
                    self.total_cost_usd = float(event.data["cost_usd"])
                    event.data["total_cost_usd"] = self.total_cost_usd
                yield event
