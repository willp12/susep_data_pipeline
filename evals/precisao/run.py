"""Roda o experimento. Cada combinação (braço, pergunta, repetição) é uma sessão nova.

    uv run python -m evals.precisao.run --out evals/precisao/results/full --reps 3

Grava ``runs.jsonl`` (uma linha por run), ``transcripts/<run_id>.json`` e
``meta.json`` no diretório de saída. Retoma de onde parou: runs que terminaram
são pulados, e os que caíram por infraestrutura (queda do CLI, timeout) rodam
de novo. Com ``--dry-run``, só mostra o plano e os prompts, sem chamar nada.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import io
import json
import logging
import os
import random
import sys
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import claude_agent_sdk
import structlog
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    query,
)
from claude_agent_sdk._cli_version import __cli_version__

from evals.precisao.arms import (
    ARMS,
    SKILL_NAME,
    STRUCTURED_OUTPUT_TOOL,
    Arm,
    build_options,
    known_datasets,
    prepare_workspace,
    scrub_inherited_env,
)
from evals.precisao.prompts import system_prompt
from evals.precisao.questions import QUESTIONS, QUESTIONS_BY_ID, Question
from evals.precisao.score import extract_answer, score_run
from evals.precisao.tools import ALLOWED_TOOLS, SERVER_NAME, ArmTools, build_server
from src.agent.glossary import build_glossary
from src.agent.providers import require_provider_credentials
from src.config import Settings, get_settings

RUN_TIMEOUT_S = 15 * 60  # o mesmo timeout do job de produção
# Campos da mensagem de init guardados em cada run, para conferir o isolamento.
_INIT_KEYS = (
    "model",
    "cwd",
    "tools",
    "mcp_servers",
    "skills",
    "plugins",
    "agents",
    "slash_commands",
    "permissionMode",
    "apiKeySource",
    "claude_code_version",
)


@dataclass(frozen=True)
class Combo:
    arm: Arm
    question: Question
    rep: int

    @property
    def run_id(self) -> str:
        return f"{self.arm.key}-{self.question.qid}-r{self.rep}"


def plan_combos(arms: list[str], qids: list[str], reps: int, seed: int) -> list[Combo]:
    """Every (arm, question, rep), shuffled with a fixed seed so no arm gets a time slot."""
    combos = [
        Combo(ARMS[a], QUESTIONS_BY_ID[q], r)
        for a in arms
        for q in qids
        for r in range(1, reps + 1)
    ]
    random.Random(seed).shuffle(combos)  # noqa: S311 -- ordem dos runs, não criptografia
    return combos


async def _prompt_stream(text: str) -> AsyncIterator[dict[str, Any]]:
    """The question as a streaming message (can_use_tool requires streaming input)."""
    yield {
        "type": "user",
        "session_id": "",
        "message": {"role": "user", "content": text},
        "parent_tool_use_id": None,
    }


def _jsonable(message: Any) -> Any:
    if dataclasses.is_dataclass(message) and not isinstance(message, type):
        return {"_type": type(message).__name__, **dataclasses.asdict(message)}
    return {"_type": type(message).__name__, "repr": repr(message)}


@dataclass
class Collector:
    """What we keep from the SDK message stream of one run."""

    transcript: list[Any] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    skill_calls: list[dict[str, Any]] = field(default_factory=list)
    init: dict[str, Any] | None = None
    result: ResultMessage | None = None
    model: str | None = None
    turn: int = 0

    def feed(self, message: Any) -> None:
        self.transcript.append(_jsonable(message))
        if isinstance(message, SystemMessage) and message.subtype == "init":
            self.init = message.data
        elif isinstance(message, AssistantMessage):
            self.turn += 1
            self.model = message.model or self.model
            for block in message.content:
                if isinstance(block, TextBlock):
                    self.texts.append(block.text)
                elif isinstance(block, ToolUseBlock) and block.name == "Skill":
                    self.skill_calls.append({"turn": self.turn, "input": block.input})
        elif isinstance(message, ResultMessage):
            self.result = message


def _names(items: Any) -> set[str]:
    """Names out of an init-message list whose items are strings or {'name': ...}."""
    names: set[str] = set()
    for item in items or []:
        if isinstance(item, str):
            names.add(item)
        elif isinstance(item, dict) and item.get("name"):
            names.add(str(item["name"]))
    return names


def isolation_problems(init: dict[str, Any] | None, arm: Arm, workspace_name: str) -> list[str]:
    """Everything in the CLI's init message that the arm should not have."""
    if not init:
        return ["sem mensagem de init"]
    problems: list[str] = []
    tools = _names(init.get("tools"))
    expected = {*ALLOWED_TOOLS, STRUCTURED_OUTPUT_TOOL, *(["Skill"] if arm.skill else [])}
    if extra := tools - expected:
        problems.append(f"tools a mais: {sorted(extra)}")
    if missing := set(ALLOWED_TOOLS) - tools:
        problems.append(f"tools faltando: {sorted(missing)}")
    if (servers := _names(init.get("mcp_servers"))) != {SERVER_NAME}:
        problems.append(f"servidores MCP: {sorted(servers)}")
    # O init lista também as skills embutidas do CLI. No B, o filtro `skills`
    # do SDK as esconde do modelo; em A e C, sem a tool Skill, nenhuma é
    # alcançável. Basta conferir que a skill do experimento chegou ao B.
    if arm.skill and SKILL_NAME not in _names(init.get("skills")):
        problems.append(f"skill {SKILL_NAME} não listada")
    if plugins := _names(init.get("plugins")):
        problems.append(f"plugins carregados: {sorted(plugins)}")
    cwd = str(init.get("cwd") or "")
    if workspace_name not in cwd:
        problems.append(f"cwd fora do diretório do run: {cwd}")
    return problems


async def run_one(
    combo: Combo,
    order: int,
    *,
    settings: Settings,
    model: str,
    max_turns: int,
    budget_usd: float,
    glossary: str,
    transcripts_dir: Path,
) -> dict[str, Any]:
    arm, question = combo.arm, combo.question
    tools = ArmTools(allowed_dataset=arm.dataset(settings), known_datasets=known_datasets(settings))
    workspace = prepare_workspace(arm)
    options = build_options(
        arm,
        settings=settings,
        model=model,
        max_turns=max_turns,
        max_budget_usd=budget_usd,
        server=build_server(tools),
        workspace=workspace,
        glossary=glossary,
    )
    record: dict[str, Any] = {
        "run_id": combo.run_id,
        "arm": arm.key,
        "arm_label": arm.label,
        "question": question.qid,
        "rep": combo.rep,
        "order": order,
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model_requested": model,
        "status": "ok",
        "error": None,
    }
    collector = Collector()

    async def consume() -> None:
        async for message in query(prompt=_prompt_stream(question.text), options=options):
            collector.feed(message)

    started = time.monotonic()
    try:
        await asyncio.wait_for(consume(), timeout=RUN_TIMEOUT_S)
    except TimeoutError:
        record["status"] = "timeout"
    except Exception as exc:
        record["status"] = "crash"
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        record["wall_s"] = round(time.monotonic() - started, 1)
        workspace.cleanup()

    result = collector.result
    answer, source = extract_answer(result.structured_output if result else None, collector.texts)
    init = collector.init
    record.update(
        {
            "model_resolved": collector.model,
            "result_subtype": result.subtype if result else None,
            "is_error": result.is_error if result else None,
            "stop_reason": result.stop_reason if result else None,
            "num_turns": result.num_turns if result else None,
            "duration_ms": result.duration_ms if result else None,
            "duration_api_ms": result.duration_api_ms if result else None,
            "cost_usd": result.total_cost_usd if result else None,
            "usage": result.usage if result else None,
            "model_usage": result.model_usage if result else None,
            "permission_denials": result.permission_denials if result else None,
            "answer": answer,
            "answer_source": source,
            "queries": [dataclasses.asdict(q) for q in tools.log.queries],
            "tool_calls": tools.log.calls,
            "skill_calls": collector.skill_calls,
            "init": {k: init[k] for k in _INIT_KEYS if k in init} if init else None,
            "isolation_problems": isolation_problems(init, arm, workspace.root.name),
        }
    )
    (transcripts_dir / f"{combo.run_id}.json").write_text(
        json.dumps(collector.transcript, default=str, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return record


def _load_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                records[record["run_id"]] = record
    return records


def _print_plan(combos: list[Combo], settings: Settings, glossary: str) -> None:
    print(f"{len(combos)} runs, nesta ordem:")
    for i, combo in enumerate(combos, 1):
        print(f"  {i:3d}. {combo.run_id}")
    for arm in sorted({c.arm for c in combos}, key=lambda a: a.key):
        prompt = system_prompt(
            arm.dataset(settings), arm.tables, glossary if arm.glossary else None
        )
        skill = f"\n(e a skill {SKILL_NAME}, que o modelo decide abrir)" if arm.skill else ""
        print(f"\n===== system prompt do braço {arm.key} ({arm.label}) ====={skill}\n{prompt}")


async def main_async(args: argparse.Namespace, scrubbed: list[str]) -> int:
    settings = get_settings()
    require_provider_credentials(settings)
    if settings.agent_provider != "anthropic":
        print("ERRO: o experimento roda no provider anthropic (AGENT_PROVIDER).", file=sys.stderr)
        return 1

    qids = [q.strip() for q in args.questions.split(",")]
    arms = [a.strip().upper() for a in args.arms.split(",")]
    combos = plan_combos(arms, qids, args.reps, args.seed)
    glossary = build_glossary(schemas={settings.gcp_bq_dataset_marts})
    if args.dry_run:
        _print_plan(combos, settings, glossary)
        return 0

    out: Path = args.out
    transcripts_dir = out / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    runs_path = out / "runs.jsonl"
    previous = _load_records(runs_path)
    finished = {rid for rid, r in previous.items() if r["status"] == "ok"}
    spent = sum(float(r.get("cost_usd") or 0) for r in previous.values())
    truth = json.loads(args.truth.read_text(encoding="utf-8")) if args.truth.exists() else None

    (out / "meta.json").write_text(
        json.dumps(
            {
                "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "model": args.model,
                "arms": arms,
                "questions": qids,
                "reps": args.reps,
                "seed": args.seed,
                "max_turns": args.max_turns,
                "budget_usd_por_run": args.budget,
                "sdk_version": claude_agent_sdk.__version__,
                "cli_version": __cli_version__,
                "env_removidas": scrubbed,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    todo = [c for c in combos if c.run_id not in finished]
    print(
        f"{len(combos)} runs no plano, {len(finished)} já feitos, {len(todo)} a rodar. "
        f"Gasto até aqui: US$ {spent:.2f}. Variáveis herdadas removidas: {len(scrubbed)}."
    )
    for i, combo in enumerate(todo, 1):
        if spent >= args.max_total_usd:
            print(
                f"Teto de US$ {args.max_total_usd:.2f} atingido; parando. Rode de novo para seguir."
            )
            break
        record = await run_one(
            combo,
            combos.index(combo) + 1,
            settings=settings,
            model=args.model,
            max_turns=args.max_turns,
            budget_usd=args.budget,
            glossary=glossary,
            transcripts_dir=transcripts_dir,
        )
        spent += float(record.get("cost_usd") or 0)
        with runs_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")

        cost = record.get("cost_usd")
        parts = [
            f"[{i}/{len(todo)}] {combo.run_id}: {record['status']}",
            "US$ ?" if cost is None else f"US$ {cost:.2f}",
            f"{record.get('num_turns')} turnos",
            f"{len(record['queries'])} queries",
            f"resposta {record['answer_source']}",
        ]
        if truth is not None:
            score = score_run(record, truth)
            parts.append("CERTO" if score.correct else f"errado ({score.label})")
        if record["skill_calls"]:
            parts.append("skill aberta")
        if record["error"]:
            parts.append(str(record["error"]))
        if record["isolation_problems"]:
            parts.append("ISOLAMENTO: " + "; ".join(record["isolation_problems"]))
        parts.append(f"total US$ {spent:.2f}")
        print(" | ".join(parts), flush=True)
    return 0


def main() -> int:
    # Antes de tudo: o .env é a única fonte de credenciais e configuração do CLI.
    scrubbed = scrub_inherited_env(os.environ)
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("evals/precisao/results/full"))
    parser.add_argument("--arms", default="A,B,C")
    parser.add_argument("--questions", default=",".join(q.qid for q in QUESTIONS))
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model", default="opus", help="o mesmo alias da produção")
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--budget", type=float, default=1.25, help="teto em US$ por run")
    parser.add_argument("--max-total-usd", type=float, default=40.0)
    parser.add_argument("--truth", type=Path, default=Path("evals/precisao/results/truth.json"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return asyncio.run(main_async(args, scrubbed))


if __name__ == "__main__":
    raise SystemExit(main())
