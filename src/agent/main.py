"""Entrypoint for the SUSEP insights agent.

Wires the BQ tools into a Claude Agent SDK run, drives one report-generation
pass, and writes `reports/YYYY-MM-DD.md`.

Run locally (needs ANTHROPIC_API_KEY in .env and the `claude` CLI installed):

    uv run python -m src.agent.main

Guardrails: a default-deny tool gate (only the three BQ tools may run), a turn
cap and a USD budget cap — both from config — on top of the per-query byte cap
already enforced in run_sql.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ToolPermissionContext,
    ToolUseBlock,
    query,
)

from src.agent.glossary import build_glossary
from src.agent.report import extract_body, render_report, write_report
from src.agent.sdk_tools import ALLOWED_TOOLS, SERVER_NAME, build_bq_server
from src.config import get_settings

log = structlog.get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "system.md"

_USER_PROMPT = (
    "Gere o relatório de insights de hoje sobre os dados SUSEP SES. "
    "Siga o processo e respeite o contrato de saída definidos no system prompt."
)


def _build_system_prompt() -> str:
    base = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    glossary = build_glossary()
    return f"{base}\n\n## Glossário (dbt docs)\n\n{glossary}\n"


async def _tool_gate(
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


async def run_agent() -> dict[str, Any]:
    """Drive one agent pass and write the report. Returns run metadata."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set — populate .env (see .env.example).")
    if not settings.gcp_project_id:
        raise RuntimeError("GCP_PROJECT_ID not set — populate .env.")

    options = ClaudeAgentOptions(
        model=settings.agent_model,
        system_prompt=_build_system_prompt(),
        mcp_servers={SERVER_NAME: build_bq_server()},
        allowed_tools=ALLOWED_TOOLS,
        can_use_tool=_tool_gate,
        permission_mode="default",
        max_turns=settings.agent_max_turns,
        max_budget_usd=settings.agent_max_budget_usd,
        env={"ANTHROPIC_API_KEY": settings.anthropic_api_key},
        cwd=str(_REPO_ROOT),
        # Don't inherit the repo's CLAUDE.md / settings into the agent run.
        setting_sources=None,
    )

    text_parts: list[str] = []
    queries_run = 0
    cost_usd: float | None = None
    model_used = settings.agent_model

    log.info("agent.run.start", model=settings.agent_model)
    async for message in query(prompt=_USER_PROMPT, options=options):
        if isinstance(message, AssistantMessage):
            model_used = message.model or model_used
            for block in message.content:
                if isinstance(block, TextBlock):
                    text_parts.append(block.text)
                elif isinstance(block, ToolUseBlock) and block.name.endswith("run_sql"):
                    queries_run += 1
        elif isinstance(message, ResultMessage):
            cost_usd = message.total_cost_usd
            log.info(
                "agent.run.result",
                cost_usd=cost_usd,
                num_turns=message.num_turns,
                is_error=message.is_error,
            )

    body = extract_body("\n".join(text_parts))
    report_date = datetime.now(UTC).date()
    rendered = render_report(
        report_date=report_date,
        model=model_used,
        body=body,
        queries_run=queries_run,
        cost_usd=cost_usd,
        ingestion_date_covered=None,
    )
    path = write_report(rendered, report_date)
    log.info("agent.run.report_written", path=str(path), queries_run=queries_run)
    return {
        "path": str(path),
        "queries_run": queries_run,
        "cost_usd": cost_usd,
        "model": model_used,
    }


def main() -> int:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )
    try:
        result = asyncio.run(run_agent())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("---")
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
