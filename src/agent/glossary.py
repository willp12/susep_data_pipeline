"""Build the column glossary the agent reads, sourced from dbt docs.

``dbt parse`` writes ``dbt/target/manifest.json`` with the model and
source descriptions defined in ``_models.yml``. We flatten the relevant nodes
into compact markdown that gets appended to the system prompt, so the agent
interprets columns from the project's own documentation rather than guessing
from names.

If the manifest is missing (docs never generated), we return a short note
telling the agent to fall back to the ``describe_table`` tool — the pipeline
still runs, just with thinner semantics.
"""

from __future__ import annotations

import json
from collections.abc import Collection
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _REPO_ROOT / "dbt" / "target" / "manifest.json"

_FALLBACK = (
    "(dbt glossary unavailable — run `dbt parse` to populate it. "
    "Use the describe_table tool to inspect columns directly.)"
)


def _format_columns(columns: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for col_name, col in columns.items():
        desc = (col.get("description") or "").strip().replace("\n", " ")
        if desc:
            lines.append(f"  - `{col_name}`: {desc}")
        else:
            lines.append(f"  - `{col_name}`")
    return lines


def _format_node(relation: str, kind: str, node: dict[str, Any]) -> list[str]:
    desc = (node.get("description") or "").strip().replace("\n", " ")
    header = f"### `{relation}` ({kind})"
    block = [header]
    if desc:
        block.append(desc)
    block.extend(_format_columns(node.get("columns", {})))
    block.append("")
    return block


def build_glossary(
    manifest_path: Path | None = None,
    *,
    schemas: Collection[str] | None = None,
) -> str:
    """Return a markdown glossary built from the dbt manifest, or a fallback note.

    ``schemas`` keeps only the sources and models that live in those datasets
    (e.g. just the marts, for an agent that may not see bronze); None keeps all.
    """
    path = manifest_path or _MANIFEST
    if not path.exists():
        return _FALLBACK

    data = json.loads(path.read_text(encoding="utf-8"))
    lines: list[str] = []

    for node in data.get("sources", {}).values():
        if schemas is not None and node["schema"] not in schemas:
            continue
        relation = f"{node['schema']}.{node['name']}"
        lines.extend(_format_node(relation, "bronze source", node))

    for node in data.get("nodes", {}).values():
        if node.get("resource_type") != "model":
            continue
        if schemas is not None and node["schema"] not in schemas:
            continue
        relation = f"{node['schema']}.{node['name']}"
        lines.extend(_format_node(relation, "dbt model", node))

    glossary = "\n".join(lines).strip()
    return glossary or _FALLBACK
