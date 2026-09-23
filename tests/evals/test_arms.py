import asyncio
from pathlib import Path

import pytest
from claude_agent_sdk import (
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)

from evals.precisao.arms import (
    ALWAYS_ON_TOOLS,
    ARMS,
    SKILL_NAME,
    SKILL_SOURCE,
    Workspace,
    build_options,
    prepare_workspace,
    scrub_inherited_env,
    tool_gate,
)
from evals.precisao.prompts import system_prompt
from evals.precisao.questions import QUESTIONS
from evals.precisao.tools import TOOL_DESCRIPTIONS, cap_message
from src.config import Settings

SETTINGS = Settings()
REPO_ROOT = Path(__file__).resolve().parents[2]

# Pedaços das regras que a skill e o mart ensinam. Nada disso pode aparecer no
# que A e B recebem de graça: prompt, pergunta, descrições das tools e erros.
RULE_TOKENS = (
    "_ingestion_date",
    "max(",
    "replace(",
    "substr(",
    "safe_cast",
    "parse_date",
    "cogrupo",
    "coramo",
    "snapshot",
    "vírgula",
    "decimal",
    "01225",
    "99999",
    "patrimonial",
    "parti",
    "gracodigo",
    "noenti",
)


def _options(key: str, workspace: Workspace) -> ClaudeAgentOptions:
    return build_options(
        ARMS[key],
        settings=SETTINGS,
        model="opus",
        max_turns=20,
        max_budget_usd=1.25,
        server={"type": "sdk", "name": "bq"},
        workspace=workspace,
        glossary="glossário do mart",
    )


def test_bronze_arms_get_the_same_prompt_and_no_rule() -> None:
    prompt_a = system_prompt(ARMS["A"].dataset(SETTINGS), ARMS["A"].tables)
    prompt_b = system_prompt(ARMS["B"].dataset(SETTINGS), ARMS["B"].tables)
    assert prompt_a == prompt_b

    free_text = [
        prompt_a,
        *TOOL_DESCRIPTIONS.values(),
        cap_message(2 * 1024**3, 1024**3),
        *(q.text for q in QUESTIONS),
    ]
    for text in free_text:
        leaked = [token for token in RULE_TOKENS if token in text.lower()]
        assert not leaked, f"regra vazando em {text[:60]!r}: {leaked}"


def test_mart_arm_prompt_carries_the_glossary() -> None:
    prompt = system_prompt(ARMS["C"].dataset(SETTINGS), ARMS["C"].tables, "glossário do mart")
    assert "susep_ses_marts.fct_seguros" in prompt
    assert "glossário do mart" in prompt
    assert "susep_ses_bronze" not in prompt


@pytest.mark.parametrize("key", ["A", "C"])
def test_arms_without_skill_load_nothing_from_disk(key: str) -> None:
    workspace = prepare_workspace(ARMS[key])
    try:
        options = _options(key, workspace)
        assert options.setting_sources == []
        assert options.tools == []
        assert options.disallowed_tools == list(ALWAYS_ON_TOOLS)
        assert options.skills == []
        assert options.strict_mcp_config is True
        assert options.cwd == str(workspace.cwd)
        assert options.env["CLAUDE_CONFIG_DIR"] == str(workspace.config_dir)
        assert options.output_format["type"] == "json_schema"
        assert list(workspace.cwd.iterdir()) == []
        assert REPO_ROOT not in workspace.root.parents
    finally:
        workspace.cleanup()
    assert not workspace.root.exists()


def test_skill_arm_loads_only_the_skill() -> None:
    workspace = prepare_workspace(ARMS["B"])
    try:
        options = _options("B", workspace)
        assert options.setting_sources == ["project"]
        assert options.tools == ["Skill"]
        assert options.skills == [SKILL_NAME]
        files = [p for p in workspace.cwd.rglob("*") if p.is_file()]
        assert files == [workspace.cwd / ".claude" / "skills" / SKILL_NAME / "SKILL.md"]
    finally:
        workspace.cleanup()


def test_skill_file_has_frontmatter() -> None:
    text = SKILL_SOURCE.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert f"name: {SKILL_NAME}\n" in text
    assert "\ndescription: " in text


def test_gate_denies_everything_off_the_list() -> None:
    gate = tool_gate(["mcp__bq__run_sql"])
    context = ToolPermissionContext()
    allowed = asyncio.run(gate("mcp__bq__run_sql", {}, context))
    denied = asyncio.run(gate("Bash", {"command": "ls"}, context))
    assert isinstance(allowed, PermissionResultAllow)
    assert isinstance(denied, PermissionResultDeny)


def test_scrub_removes_what_a_parent_claude_session_exports() -> None:
    env = {
        "CLAUDE_EFFORT": "max",
        "CLAUDECODE": "1",
        "ANTHROPIC_BASE_URL": "http://localhost:1",
        "USE_STAGING_OAUTH": "1",
        "MCP_SERVER_CONNECTION_BATCH_SIZE": "3",
        "PATH": "/bin",
        "GCP_PROJECT_ID": "p",
    }
    removed = scrub_inherited_env(env)
    assert env == {"PATH": "/bin", "GCP_PROJECT_ID": "p"}
    assert "CLAUDE_EFFORT" in removed
