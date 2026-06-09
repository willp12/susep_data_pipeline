from pathlib import Path

from src.agent.queries import render_queries_appendix, write_queries_appendix
from src.agent.sdk_tools import QueryLogEntry


def _ok_entry(no: int, sql: str = "SELECT 1") -> QueryLogEntry:
    return QueryLogEntry(
        query_no=no,
        sql=sql,
        status="ok",
        bytes_processed=2 * 1024**2,
        row_count=12,
        cache_hit=False,
    )


def test_render_appendix_numbers_queries_in_order() -> None:
    out = render_queries_appendix(
        "2026-06-09",
        [_ok_entry(1, "SELECT a FROM t"), _ok_entry(2, "SELECT b FROM t")],
    )
    assert "# Apêndice de queries — 2026-06-09" in out
    assert out.index("## Query 1") < out.index("## Query 2")
    assert "SELECT a FROM t" in out
    assert "12 linha(s), 2.0 MiB processados" in out


def test_render_appendix_keeps_failed_queries() -> None:
    rejected = QueryLogEntry(
        query_no=1,
        sql="SELECT * FROM huge",
        status="rejected",
        error="over the cap",
    )
    out = render_queries_appendix("2026-06-09", [rejected])
    assert "status: rejected — over the cap" in out
    assert "SELECT * FROM huge" in out


def test_write_appendix_lands_in_queries_subdir(tmp_path: Path) -> None:
    path = write_queries_appendix("conteudo", "2026-06-09_2", reports_dir=tmp_path)
    assert path == tmp_path / "queries" / "2026-06-09_2.sql.md"
    assert path.read_text(encoding="utf-8") == "conteudo"
