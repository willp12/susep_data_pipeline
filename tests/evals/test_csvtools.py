import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from evals.precisao.csvtools import CsvTools

FILES = ("fato.csv", "cadastro.csv")


@pytest.fixture
def tools(tmp_path: Path) -> Iterator[CsvTools]:
    folder = tmp_path / "dados"
    folder.mkdir()
    (folder / "fato.csv").write_text(
        "damesano;premio\n202401;100\n202401;50,5\n202402;25\n", encoding="ascii"
    )
    # Windows-1252 de verdade: 0x96 é um travessão tipográfico.
    (folder / "cadastro.csv").write_bytes(b"codigo;nome\n01;SEGURADORA \x96 ABC\n")
    (tmp_path / "segredo.csv").write_text("x\n1\n", encoding="ascii")
    csv = CsvTools(data_dir=folder, files=FILES, max_rows=2)
    yield csv
    csv.close()


def _text(result: dict[str, Any]) -> str:
    return str(result["content"][0]["text"])


def test_list_files_reports_only_the_known_files(tools: CsvTools) -> None:
    listed = json.loads(_text(tools.list_files({})))
    assert [f["arquivo"] for f in listed] == list(FILES)
    assert all(f["bytes"] > 0 for f in listed)


def test_head_file_shows_bytes_as_a_utf8_terminal_would(tools: CsvTools) -> None:
    head = json.loads(_text(tools.head_file({"arquivo": "cadastro.csv", "n": 2})))
    assert head["linhas"][1] == "01;SEGURADORA � ABC"
    assert tools.head_file({"arquivo": "segredo.csv", "n": 1})["is_error"] is True
    assert tools.head_file({"arquivo": "fato.csv", "n": 99})["is_error"] is True


def test_known_names_are_resolved_and_anything_else_is_left_alone(tools: CsvTools) -> None:
    sql = (
        "SELECT * FROM read_csv('fato.csv') JOIN read_csv('./CADASTRO.csv') USING (x) WHERE a = 'b'"
    )
    resolved = tools.resolve_files(sql)
    assert f"'{(tools.data_dir / 'fato.csv').as_posix()}'" in resolved
    assert f"'{(tools.data_dir / 'cadastro.csv').as_posix()}'" in resolved
    assert "'b'" in resolved
    assert tools.resolve_files("SELECT * FROM read_csv('../segredo.csv')") == (
        "SELECT * FROM read_csv('../segredo.csv')"
    )


def test_sql_reads_the_folder_and_truncates_long_results(tools: CsvTools) -> None:
    payload = json.loads(
        _text(tools.sql({"sql": "SELECT * FROM read_csv('fato.csv', all_varchar=true)"}))
    )
    assert payload["query_no"] == 1
    assert len(payload["rows"]) == 2
    assert "truncado" in payload
    assert tools.log.queries[0].status == "ok"
    assert tools.log.queries[0].elapsed_ms is not None


def test_sql_cannot_leave_the_folder_or_write(tools: CsvTools) -> None:
    outside = (tools.data_dir.parent / "segredo.csv").as_posix()
    for sql in (
        f"SELECT * FROM read_csv('{outside}')",
        "SELECT * FROM read_csv('../segredo.csv')",
        f"SELECT * FROM read_csv('{tools.data_dir.as_posix()}/../segredo.csv')",
        "SELECT * FROM read_csv('https://example.com/a.csv')",
    ):
        result = tools.sql({"sql": sql})
        assert result["is_error"] is True, sql
    written = tools.sql({"sql": "COPY (SELECT 1) TO 'saida.csv'"})
    assert written["is_error"] is True
    assert tools.log.queries[-1].status == "rejected"


def test_errors_keep_duckdb_hints_but_not_the_local_path(tools: CsvTools) -> None:
    result = tools.sql({"sql": "SELECT * FROM read_csv('cadastro.csv')"})
    message = _text(result)
    assert result["is_error"] is True
    assert "unicode" in message.lower()
    assert tools.data_dir.as_posix() not in message
    assert "LINE 1" not in message


def test_a_slow_query_is_interrupted(tmp_path: Path) -> None:
    folder = tmp_path / "vazia"
    folder.mkdir()
    (folder / "fato.csv").write_text("x\n1\n", encoding="ascii")
    slow = CsvTools(data_dir=folder, files=("fato.csv",), timeout_s=0.3)
    try:
        result = slow.sql(
            {"sql": "SELECT SUM(a.range * b.range) FROM range(100000) a, range(100000) b"}
        )
    finally:
        slow.close()
    assert result["is_error"] is True
    assert "interrompida" in _text(result)
