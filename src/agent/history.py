"""Report history — gives the agent continuity across runs.

Published reports live in the GCS reports bucket (see ``publisher``), not in
the repo. The always-injected digest is built from ``manifest.json`` alone
(dates + insight titles — one small GET); the full text of any prior report is
fetched on demand via the ``read_report`` tool.

Unlike the old repo-folder history, a published report is visible to the very
next run — there is no PR-merge lag.
"""

from __future__ import annotations

import re

from src.agent.publisher import ReportStore

# Matches YYYY-MM-DD and same-day reruns YYYY-MM-DD_2, _3, …
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:_\d+)?$")

_NO_HISTORY = "(Nenhum report anterior — este é o primeiro. Faça um baseline amplo do mercado.)"


def build_history_digest(
    *,
    store: ReportStore | None = None,
    max_reports: int = 21,
) -> str:
    """Build a compact markdown digest of recent reports' insight titles."""
    target_store = store or ReportStore()
    entries = target_store.load_manifest().get("reports", [])
    entries = sorted(entries, key=lambda e: str(e["stem"]), reverse=True)[:max_reports]

    blocks: list[str] = []
    for entry in entries:
        titles = entry.get("titles") or []
        if not titles:
            continue
        lines = [f"### {entry['stem']}"]
        lines.extend(f"- {title}" for title in titles)
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks) if blocks else _NO_HISTORY


def read_report(report_date: str, *, store: ReportStore | None = None) -> str:
    """Return the full markdown of a previous report by stem (YYYY-MM-DD[_n]).

    Reports newer than the analysis/SQL split keep their queries in a separate
    appendix; when the manifest points to one it's appended, so a deep-dive
    still sees the SQL behind the numbers. Backfilled (older) reports carry
    the SQL inline and have no appendix.
    """
    if not _DATE_RE.match(report_date):
        raise ValueError(f"report_date must be YYYY-MM-DD, got {report_date!r}")
    target_store = store or ReportStore()

    manifest = target_store.load_manifest()
    entry = next(
        (e for e in manifest.get("reports", []) if e["stem"] == report_date),
        None,
    )
    if entry is None:
        raise FileNotFoundError(f"No report found for {report_date}")

    text = target_store.download_text(entry["report_path"])
    if entry.get("queries_path"):
        text = f"{text}\n\n---\n\n{target_store.download_text(entry['queries_path'])}"
    return text
