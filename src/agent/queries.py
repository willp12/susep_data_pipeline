"""Render and persist the SQL appendix of a report.

The report body carries only the analysis; the SQL behind it lives in a
sibling appendix built deterministically from the run_sql query log (see
``sdk_tools.QueryLogEntry``) — the model never writes the appendix itself.
Insights cite queries by ``query_no``, which is the 1-based execution order.

Local layout (mirrors the future GCS layout): ``reports/queries/<stem>.sql.md``
next to ``reports/<stem>.md``.
"""

from __future__ import annotations

from pathlib import Path

from src.agent.sdk_tools import QueryLogEntry

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPORTS_DIR = _REPO_ROOT / "reports"

_MIB = 1024**2


def _entry_caption(entry: QueryLogEntry) -> str:
    if entry.status == "ok":
        mib = (entry.bytes_processed or 0) / _MIB
        cache = ", cache hit" if entry.cache_hit else ""
        return f"_{entry.row_count} linha(s), {mib:.1f} MiB processados{cache}_"
    return f"_status: {entry.status} — {entry.error}_"


def render_queries_appendix(report_stem: str, entries: list[QueryLogEntry]) -> str:
    """Assemble the appendix markdown: every query of the run, numbered.

    Rejected/failed queries are kept (with their error) — the appendix is the
    faithful log of what the agent ran, not just what worked.
    """
    parts = [
        f"# Apêndice de queries — {report_stem}",
        "",
        f"Queries executadas pelo agente na geração de `{report_stem}.md`, na "
        "ordem em que rodaram. Os insights citam estas queries por número.",
        "",
    ]
    for entry in entries:
        parts.extend(
            [
                f"## Query {entry.query_no}",
                "",
                _entry_caption(entry),
                "",
                "```sql",
                entry.sql.strip(),
                "```",
                "",
            ]
        )
    return "\n".join(parts)


def write_queries_appendix(
    text: str,
    report_stem: str,
    *,
    reports_dir: Path | None = None,
) -> Path:
    """Write ``queries/<stem>.sql.md``. The stem is already unique per run
    (write_report's non-overwrite suffix), so a plain write is safe."""
    target_dir = (reports_dir or _REPORTS_DIR) / "queries"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{report_stem}.sql.md"
    path.write_text(text, encoding="utf-8")
    return path
