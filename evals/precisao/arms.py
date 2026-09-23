"""Os três braços do experimento e o ClaudeAgentOptions de cada um.

O isolamento é o ponto: nada entra no agente além do que o braço prevê.

* Disco: a produção passa ``setting_sources=None``, que no SDK 0.2.82 carrega
  as configurações de usuário, projeto e local. Aqui, A e C usam ``[]`` e B
  carrega só "project", num diretório temporário que contém apenas a skill.
  ``CLAUDE_CONFIG_DIR`` aponta para um diretório vazio, como a home do runner
  do CI.
* Tools: as internas do Claude Code ficam desligadas (``tools=[]``), menos a
  ``Skill`` no B, e só o servidor MCP do experimento é carregado.
* Ambiente: ``scrub_inherited_env`` tira as variáveis que um Claude Code pai
  exporta (endpoint, auth, esforço), para o CLI filho ver o que o CI vê.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Collection, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from claude_agent_sdk import (
    CanUseTool,
    ClaudeAgentOptions,
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from evals.precisao.prompts import system_prompt
from evals.precisao.questions import ANSWER_SCHEMA
from evals.precisao.tools import ALLOWED_TOOLS, SERVER_NAME
from src.agent.providers import provider_env
from src.config import Settings

SKILL_NAME = "susep-bronze"
SKILL_SOURCE = Path(__file__).resolve().parent / "skill" / SKILL_NAME / "SKILL.md"
# Tool interna do CLI que entrega a resposta quando há output_format.
STRUCTURED_OUTPUT_TOOL = "StructuredOutput"
# Tools que o CLI 2.1.142 carrega mesmo com tools=[] (recursos da conta por
# assinatura). O gate já as negaria; tirá-las deixa o contexto dos braços limpo.
ALWAYS_ON_TOOLS = ("Monitor", "PushNotification", "RemoteTrigger")

BRONZE_TABLES = (
    "ses_seguros",
    "ses_ramos",
    "ses_gruposramos",
    "ses_cias",
    "ses_grupos_economicos",
    "ingestion_log",
)
MART_TABLES = (
    "fct_seguros",
    "dim_ramo",
    "dim_grupo_ramo",
    "dim_entidade",
    "dim_grupo_economico",
    "dim_cnseg",
)


@dataclass(frozen=True)
class Arm:
    key: str
    label: str
    layer: Literal["bronze", "marts"]
    skill: bool
    glossary: bool

    @property
    def tables(self) -> tuple[str, ...]:
        return BRONZE_TABLES if self.layer == "bronze" else MART_TABLES

    def dataset(self, settings: Settings) -> str:
        if self.layer == "bronze":
            return settings.gcp_bq_dataset_bronze
        return settings.gcp_bq_dataset_marts


ARMS: dict[str, Arm] = {
    "A": Arm("A", "bronze cru", "bronze", skill=False, glossary=False),
    "B": Arm("B", "bronze + skill", "bronze", skill=True, glossary=False),
    "C": Arm("C", "mart dbt", "marts", skill=False, glossary=True),
}


def known_datasets(settings: Settings) -> tuple[str, ...]:
    return (
        settings.gcp_bq_dataset_bronze,
        settings.gcp_bq_dataset_staging,
        settings.gcp_bq_dataset_marts,
    )


@dataclass(frozen=True)
class Workspace:
    """Temporary directories of one run, outside any repo. Remove ``root`` after."""

    root: Path
    cwd: Path  # empty, or holding only the skill for arm B
    config_dir: Path  # CLAUDE_CONFIG_DIR: an empty home, like the CI runner's

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def prepare_workspace(arm: Arm) -> Workspace:
    root = Path(tempfile.mkdtemp(prefix=f"susep-eval-{arm.key}-"))
    workspace = Workspace(root=root, cwd=root / "cwd", config_dir=root / "home")
    workspace.cwd.mkdir()
    workspace.config_dir.mkdir()
    if arm.skill:
        target = workspace.cwd / ".claude" / "skills" / SKILL_NAME / "SKILL.md"
        target.parent.mkdir(parents=True)
        shutil.copyfile(SKILL_SOURCE, target)
    return workspace


def tool_gate(allowed: Collection[str]) -> CanUseTool:
    """Default-deny, like the production gate, with this arm's tool list."""
    allowed_names = frozenset(allowed)

    async def gate(
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResult:
        if tool_name in allowed_names:
            return PermissionResultAllow()
        return PermissionResultDeny(message=f"A tool '{tool_name}' não está disponível.")

    return gate


def build_options(
    arm: Arm,
    *,
    settings: Settings,
    model: str,
    max_turns: int,
    max_budget_usd: float,
    server: Any,
    workspace: Workspace,
    glossary: str | None,
) -> ClaudeAgentOptions:
    allowed = [*ALLOWED_TOOLS, STRUCTURED_OUTPUT_TOOL, *(["Skill"] if arm.skill else [])]
    env = {**provider_env(settings), "CLAUDE_CONFIG_DIR": str(workspace.config_dir)}
    return ClaudeAgentOptions(
        model=model,
        system_prompt=system_prompt(
            arm.dataset(settings), arm.tables, glossary if arm.glossary else None
        ),
        mcp_servers={SERVER_NAME: server},
        strict_mcp_config=True,
        tools=["Skill"] if arm.skill else [],
        disallowed_tools=list(ALWAYS_ON_TOOLS),
        allowed_tools=list(ALLOWED_TOOLS),
        skills=[SKILL_NAME] if arm.skill else [],
        setting_sources=["project"] if arm.skill else [],
        can_use_tool=tool_gate(allowed),
        permission_mode="default",
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        env=env,
        cwd=str(workspace.cwd),
        output_format={"type": "json_schema", "schema": ANSWER_SCHEMA},
    )


# Variáveis que um Claude Code pai (o app desktop, uma sessão de terminal)
# exporta e que o CLI filho herdaria: mudariam endpoint, auth, esforço e o
# comportamento do MCP. O runner do CI não tem nenhuma delas. As credenciais
# voltam pelo .env, via provider_env.
_INHERITED_PREFIXES = ("CLAUDE", "ANTHROPIC", "OTEL_", "MCP_")
_INHERITED_NAMES = frozenset(
    {
        "AI_AGENT",
        "API_TIMEOUT_MS",
        "BAGGAGE",
        "DISABLE_AUTOUPDATER",
        "DISABLE_MICROCOMPACT",
        "SENTRY-TRACE",
        "TRACEPARENT",
        "TRACESTATE",
        "USE_LOCAL_OAUTH",
        "USE_STAGING_OAUTH",
    }
)


def scrub_inherited_env(environ: MutableMapping[str, str]) -> list[str]:
    """Drop, in place, the variables a parent Claude Code session exported.

    Must run before ``get_settings()``, which then loads the credentials from
    .env. Returns the names removed (never the values).
    """
    names = sorted(
        key
        for key in environ
        if key.upper().startswith(_INHERITED_PREFIXES) or key.upper() in _INHERITED_NAMES
    )
    for key in names:
        del environ[key]
    return names
