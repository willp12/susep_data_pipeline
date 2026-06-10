"""Terminal REPL for the analyst chat.

    uv run python -m src.chat.cli

Prerequisites: the reports bucket populated (manifest), GCP ADC credentials,
and either ANTHROPIC_API_KEY or AGENT_PROVIDER=local with LM Studio serving a
model. `dbt parse` enriches the glossary but isn't required.

Commands inside the REPL: /reports re-prints the history digest, /custo shows
the session cost so far, /sair exits.
"""

from __future__ import annotations

import asyncio
import sys

import structlog

from src.agent.history import build_history_digest
from src.agent.publisher import ReportStore
from src.chat.session import ChatSession
from src.config import get_settings

_PROMPT = "\nvocê> "
_EXIT_COMMANDS = {"/sair", "/exit", "/quit"}


def _print_banner(provider: str, model: str, digest: str) -> None:
    print("=" * 72)
    print(f"Chat analítico SUSEP SES — provider: {provider} | modelo: {model}")
    print("Comandos: /reports (temas já cobertos), /custo, /sair")
    print("=" * 72)
    print("\nTemas recentes:\n")
    print(digest)


async def _amain() -> int:
    settings = get_settings()
    store = ReportStore()
    digest = build_history_digest(store=store, max_reports=8)
    _print_banner(settings.agent_provider, settings.agent_model, digest)

    async with ChatSession(store=store) as session:
        while True:
            try:
                question = (await asyncio.to_thread(input, _PROMPT)).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not question:
                continue
            if question.lower() in _EXIT_COMMANDS:
                break
            if question.lower() == "/reports":
                print(build_history_digest(store=store))
                continue
            if question.lower() == "/custo":
                print(f"custo da sessão: US$ {session.total_cost_usd:.4f}")
                continue

            print()
            async for event in session.ask(question):
                if event.kind == "text":
                    print(event.text)
                elif event.kind == "tool":
                    print(f"  ⚙ {event.text}")
                elif event.kind == "result" and event.data:
                    if event.data.get("is_error"):
                        print("  [a resposta terminou com erro — veja acima]")
                    cost = event.data.get("cost_usd")
                    # Local runs are free; the SDK still reports a fictitious
                    # cost computed from token counts, so don't show it.
                    if cost and session.provider == "anthropic":
                        print(f"  (custo da sessão até aqui: US$ {float(cost):.4f})")

    if session.total_cost_usd and session.provider == "anthropic":
        print(f"\ncusto total da sessão: US$ {session.total_cost_usd:.4f}")
    print("até a próxima!")
    return 0


def main() -> int:
    # Windows consoles often default to a legacy code page; the digest and the
    # answers are full of accents, so force UTF-8 where reconfigure exists.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure and (stream.encoding or "").lower() != "utf-8":
            reconfigure(encoding="utf-8")

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        # Chat is interactive — keep the console clean; warnings still show.
        wrapper_class=structlog.make_filtering_bound_logger(30),
    )
    try:
        return asyncio.run(_amain())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
