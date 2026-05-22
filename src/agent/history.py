"""Report history — gives the agent continuity across runs.

Past reports are committed under ``reports/YYYY-MM-DD.md``. We build a compact
digest (date + the insight titles of each report) and inject it into the system
prompt, so the agent knows what's already been covered and can either deep-dive
a prior thread or pick a genuinely new angle instead of repeating itself.

Only titles go into the always-injected digest (cheap). The full text of any
prior report is fetched on demand via the ``read_report`` tool.

History reflects reports merged to the branch the workflow checks out — open
report PRs aren't visible yet.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPORTS_DIR = _REPO_ROOT / "reports"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HEADER_RE = re.compile(r"^###\s+(.+)$", re.MULTILINE)

_NO_HISTORY = "(Nenhum report anterior — este é o primeiro. Faça um baseline amplo do mercado.)"


def _report_files(reports_dir: Path) -> list[Path]:
    """Return report files (YYYY-MM-DD.md), most recent first."""
    return sorted(
        (p for p in reports_dir.glob("*.md") if _DATE_RE.match(p.stem)),
        key=lambda p: p.stem,
        reverse=True,
    )


def build_history_digest(
    *,
    reports_dir: Path | None = None,
    exclude: date | None = None,
    max_reports: int = 21,
) -> str:
    """Build a compact markdown digest of recent reports' insight titles."""
    target_dir = reports_dir or _REPORTS_DIR
    if not target_dir.exists():
        return _NO_HISTORY

    files = _report_files(target_dir)
    if exclude is not None:
        files = [p for p in files if p.stem != exclude.isoformat()]
    files = files[:max_reports]

    blocks: list[str] = []
    for path in files:
        titles = _HEADER_RE.findall(path.read_text(encoding="utf-8"))
        if not titles:
            continue
        lines = [f"### {path.stem}"]
        lines.extend(f"- {title.strip()}" for title in titles)
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks) if blocks else _NO_HISTORY


def read_report(report_date: str, *, reports_dir: Path | None = None) -> str:
    """Return the full markdown of a previous report by date (YYYY-MM-DD)."""
    if not _DATE_RE.match(report_date):
        raise ValueError(f"report_date must be YYYY-MM-DD, got {report_date!r}")
    target_dir = reports_dir or _REPORTS_DIR
    path = target_dir / f"{report_date}.md"
    if not path.exists():
        raise FileNotFoundError(f"No report found for {report_date}")
    return path.read_text(encoding="utf-8")
