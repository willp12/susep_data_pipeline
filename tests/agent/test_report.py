from datetime import date
from pathlib import Path

from src.agent.report import (
    extract_body,
    render_report,
    reserve_report_path,
    write_report,
)


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


def test_render_report_references_queries_file() -> None:
    out = render_report(
        report_date=date(2026, 6, 9),
        model="sonnet",
        body="x",
        queries_run=3,
        cost_usd=None,
        ingestion_date_covered=None,
        queries_file="queries/2026-06-09.sql.md",
    )
    assert "queries_file: queries/2026-06-09.sql.md" in out


def test_render_report_queries_file_defaults_to_null() -> None:
    out = render_report(
        report_date=date(2026, 6, 9),
        model="sonnet",
        body="x",
        queries_run=0,
        cost_usd=None,
        ingestion_date_covered=None,
    )
    assert "queries_file: null" in out


def test_reserve_report_path_skips_existing(tmp_path: Path) -> None:
    (tmp_path / "2026-06-09.md").write_text("x", encoding="utf-8")
    path = reserve_report_path(date(2026, 6, 9), reports_dir=tmp_path)
    assert path == tmp_path / "2026-06-09_2.md"
    # Reserving doesn't write anything.
    assert not path.exists()


def test_write_report_writes_dated_file(tmp_path: Path) -> None:
    path = write_report("hello", date(2026, 5, 20), reports_dir=tmp_path)
    assert path == tmp_path / "2026-05-20.md"
    assert path.read_text(encoding="utf-8") == "hello"


def test_write_report_never_overwrites_same_day(tmp_path: Path) -> None:
    p1 = write_report("first", date(2026, 5, 20), reports_dir=tmp_path)
    p2 = write_report("second", date(2026, 5, 20), reports_dir=tmp_path)
    p3 = write_report("third", date(2026, 5, 20), reports_dir=tmp_path)

    assert p1 == tmp_path / "2026-05-20.md"
    assert p2 == tmp_path / "2026-05-20_2.md"
    assert p3 == tmp_path / "2026-05-20_3.md"
    # The original is preserved untouched.
    assert p1.read_text(encoding="utf-8") == "first"
    assert p2.read_text(encoding="utf-8") == "second"
