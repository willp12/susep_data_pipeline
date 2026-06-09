"""Render and persist the agent's daily report as `reports/YYYY-MM-DD.md`.

The agent returns the report body wrapped in ===REPORT START===/===REPORT END===
markers. We extract that, prepend a YAML frontmatter block with run metadata
(model, cost, queries, snapshot date) and write the file.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPORTS_DIR = _REPO_ROOT / "reports"

_MARKER_RE = re.compile(
    r"===REPORT START===\s*(?P<body>.*?)\s*===REPORT END===",
    re.DOTALL,
)


def extract_body(agent_text: str) -> str:
    """Pull the report body out of the marker block.

    Falls back to the full text (stripped) if markers are absent, so a slightly
    misbehaving model still yields a usable report.
    """
    match = _MARKER_RE.search(agent_text)
    if match:
        return match.group("body").strip()
    return agent_text.strip()


def render_report(
    *,
    report_date: date,
    model: str,
    body: str,
    queries_run: int,
    cost_usd: float | None,
    ingestion_date_covered: str | None,
    queries_file: str | None = None,
) -> str:
    """Assemble frontmatter + body into the final markdown document.

    ``queries_file`` is the report-relative path of the SQL appendix (e.g.
    ``queries/2026-06-09.sql.md``) when the run produced one.
    """
    cost_str = f"{cost_usd:.4f}" if cost_usd is not None else "null"
    covered = ingestion_date_covered or "null"
    frontmatter = "\n".join(
        [
            "---",
            f"date: {report_date.isoformat()}",
            f"model: {model}",
            f"ingestion_date_covered: {covered}",
            f"queries_run: {queries_run}",
            f"cost_usd: {cost_str}",
            f"queries_file: {queries_file or 'null'}",
            "generated_by: susep-insights-agent",
            "---",
            "",
            f"# Insights SUSEP SES — {report_date.isoformat()}",
            "",
        ]
    )
    return f"{frontmatter}{body}\n"


def reserve_report_path(
    report_date: date,
    *,
    reports_dir: Path | None = None,
) -> Path:
    """Pick the report path without overwriting an existing one.

    The first report of a day is `reports/YYYY-MM-DD.md`; later same-day runs
    (e.g. manual workflow_dispatch) get a numeric suffix — `YYYY-MM-DD_2.md`,
    `_3.md`, … — so no previous report is ever clobbered. The path is only
    chosen here (single-process run, no race); the caller writes to it.
    """
    target_dir = reports_dir or _REPORTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    base = report_date.isoformat()
    path = target_dir / f"{base}.md"
    suffix = 2
    while path.exists():
        path = target_dir / f"{base}_{suffix}.md"
        suffix += 1
    return path


def write_report(
    text: str,
    report_date: date,
    *,
    reports_dir: Path | None = None,
) -> Path:
    """Write the report to the next non-clobbering dated path."""
    path = reserve_report_path(report_date, reports_dir=reports_dir)
    path.write_text(text, encoding="utf-8")
    return path
