from datetime import date
from pathlib import Path

from src.agent.report import extract_body, render_report, write_report


def test_extract_body_pulls_marker_block() -> None:
    text = (
        "let me think about this\n"
        "===REPORT START===\n## Sumário\nconteúdo\n===REPORT END===\n"
        "trailing chatter"
    )
    assert extract_body(text) == "## Sumário\nconteúdo"


def test_extract_body_falls_back_without_markers() -> None:
    assert extract_body("  só texto cru  ") == "só texto cru"


def test_render_report_has_frontmatter_and_body() -> None:
    out = render_report(
        report_date=date(2026, 5, 20),
        model="claude-sonnet-4-6",
        body="## Insights\n...",
        queries_run=7,
        cost_usd=0.1234,
        ingestion_date_covered="2026-04-26",
    )
    assert out.startswith("---\n")
    assert "date: 2026-05-20" in out
    assert "model: claude-sonnet-4-6" in out
    assert "queries_run: 7" in out
    assert "cost_usd: 0.1234" in out
    assert "ingestion_date_covered: 2026-04-26" in out
    assert "## Insights" in out


def test_render_report_handles_null_cost() -> None:
    out = render_report(
        report_date=date(2026, 5, 20),
        model="sonnet",
        body="x",
        queries_run=0,
        cost_usd=None,
        ingestion_date_covered=None,
    )
    assert "cost_usd: null" in out
    assert "ingestion_date_covered: null" in out


def test_write_report_writes_dated_file(tmp_path: Path) -> None:
    path = write_report("hello", date(2026, 5, 20), reports_dir=tmp_path)
    assert path == tmp_path / "2026-05-20.md"
    assert path.read_text(encoding="utf-8") == "hello"
