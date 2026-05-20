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
) -> str:
    """Assemble frontmatter + body into the final markdown document."""
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
            "generated_by: susep-insights-agent",
            "---",
            "",
            f"# Insights SUSEP SES — {report_date.isoformat()}",
            "",
        ]
    )
    return f"{frontmatter}{body}\n"


def write_report(
    text: str,
    report_date: date,
    *,
    reports_dir: Path | None = None,
) -> Path:
    """Write the rendered report to `reports/YYYY-MM-DD.md` and return its path."""
    target_dir = reports_dir or _REPORTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{report_date.isoformat()}.md"
    path.write_text(text, encoding="utf-8")
    return path
