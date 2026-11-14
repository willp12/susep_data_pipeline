"""Tools do braço D: o agente lê os CSVs crus da SUSEP com SQL no DuckDB.

As mesmas proteções das tools do BigQuery, adaptadas a arquivo local:

* uma única instrução SELECT/WITH, pela mesma guarda de ``bq_query``;
* DuckDB sem acesso externo: lê só a pasta dos dados, sem rede, sem extensões
  e com a configuração travada. Como o IAM no BigQuery, é a fronteira de
  verdade; a guarda de forma é defesa em profundidade;
* timeout por query e teto de linhas devolvidas;
* o agente escreve ``read_csv('Ses_seguros.csv')``: a tool troca o nome de cada
  arquivo conhecido pelo caminho absoluto, porque o DuckDB recusa caminho
  relativo quando o acesso externo está desligado.

As descrições das tools são neutras: nada sobre encoding, separador ou tipos.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any

import duckdb
from claude_agent_sdk import create_sdk_mcp_server, tool

from evals.precisao.tools import QueryRecord, ToolLog
from src.agent.tools._serde import jsonable_row
from src.agent.tools.bq_query import NonReadOnlyQueryError, _assert_read_only

CSV_SERVER_NAME = "csv"
# Os arquivos do zip que correspondem às tabelas que o braço A lê na bronze.
CSV_FILES = (
    "Ses_seguros.csv",
    "Ses_ramos.csv",
    "ses_gruposramos.csv",
    "Ses_cias.csv",
    "Ses_grupos_economicos.csv",
)
MAX_ROWS_RETURNED = 500
MAX_HEAD_LINES = 50
QUERY_TIMEOUT_S = 120

CSV_TOOL_DESCRIPTIONS = {
    "list_files": "Lista os arquivos da pasta, com o tamanho em bytes. Sem custo.",
    "head_file": "As primeiras n linhas de um arquivo, como texto (1 a 50). Sem custo.",
    "run_sql": (
        "Executa SQL somente leitura no DuckDB. Leia os arquivos com "
        "read_csv('<arquivo>'). Devolve as linhas e um query_no. Queries com mais "
        f"de {QUERY_TIMEOUT_S} s são interrompidas."
    ),
}
CSV_ALLOWED_TOOLS = [f"mcp__{CSV_SERVER_NAME}__{name}" for name in CSV_TOOL_DESCRIPTIONS]

_STRING_LITERAL = re.compile(r"'((?:[^']|'')*)'")


def _ok(payload: Any) -> dict[str, Any]:
    text = json.dumps(payload, default=str, ensure_ascii=False)
    return {"content": [{"type": "text", "text": text}]}


def _error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "is_error": True}


def _sql_str(value: str) -> str:
    return value.replace("'", "''")


class CsvTools:
    """Handlers of the three arm D tools for one run, confined to one folder."""

    def __init__(
        self,
        *,
        data_dir: Path,
        files: Sequence[str] = CSV_FILES,
        max_rows: int = MAX_ROWS_RETURNED,
        timeout_s: float = QUERY_TIMEOUT_S,
        memory_limit: str = "4GB",
    ) -> None:
        self.data_dir = data_dir.resolve()
        self.files = {name.lower(): name for name in files}
        self.max_rows = max_rows
        self.timeout_s = timeout_s
        self.memory_limit = memory_limit
        self.log = ToolLog()
        self._con: duckdb.DuckDBPyConnection | None = None

    # --- DuckDB -------------------------------------------------------------

    def _connection(self) -> duckdb.DuckDBPyConnection:
        if self._con is None:
            con = duckdb.connect(
                ":memory:",
                config={
                    "autoinstall_known_extensions": False,
                    "autoload_known_extensions": False,
                    "memory_limit": self.memory_limit,
                },
            )
            folder = _sql_str(self.data_dir.as_posix())
            con.execute(f"SET allowed_directories = ['{folder}']")
            con.execute("SET enable_external_access = false")
            con.execute("SET lock_configuration = true")
            self._con = con
        return self._con

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None

    def _path(self, name: str) -> str:
        return (self.data_dir / self.files[name.lower()]).as_posix()

    def resolve_files(self, sql: str) -> str:
        """Swap each quoted known file name for its absolute path; leave the rest."""

        def swap(match: re.Match[str]) -> str:
            literal = match.group(1).replace("''", "'")
            name = literal[2:] if literal.startswith("./") else literal
            if name.lower() in self.files:
                return f"'{_sql_str(self._path(name))}'"
            return match.group(0)

        return _STRING_LITERAL.sub(swap, sql)

    def _tidy(self, message: str) -> str:
        """Show file names, not absolute paths, in error messages.

        DuckDB also echoes the offending SQL line, which here is the rewritten
        one with absolute paths; that echo is dropped.
        """
        message = message.split("\nLINE ")[0].rstrip()
        return message.replace(self.data_dir.as_posix() + "/", "").replace(
            str(self.data_dir) + "\\", ""
        )

    # --- tools --------------------------------------------------------------

    def list_files(self, args: dict[str, Any]) -> dict[str, Any]:
        self.log.calls.append({"tool": "list_files"})
        return _ok(
            [
                {"arquivo": name, "bytes": (self.data_dir / name).stat().st_size}
                for name in self.files.values()
            ]
        )

    def head_file(self, args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("arquivo") or args.get("file") or "")
        n = int(args.get("n", 10))
        self.log.calls.append({"tool": "head_file", "arquivo": name, "n": n})
        if name.lower() not in self.files:
            return _error(f"O arquivo `{name}` não está disponível.")
        if not 1 <= n <= MAX_HEAD_LINES:
            return _error(f"n precisa estar entre 1 e {MAX_HEAD_LINES}.")
        lines: list[str] = []
        with (self.data_dir / self.files[name.lower()]).open("rb") as fh:
            for raw in fh:
                # Como um `head` num terminal UTF-8: bytes inválidos viram �.
                lines.append(raw.decode("utf-8", errors="replace").rstrip("\r\n")[:400])
                if len(lines) >= n:
                    break
        return _ok({"arquivo": self.files[name.lower()], "linhas": lines})

    def sql(self, args: dict[str, Any]) -> dict[str, Any]:
        sql = str(args["sql"])
        record = QueryRecord(query_no=len(self.log.queries) + 1, sql=sql, status="error")
        self.log.queries.append(record)
        try:
            _assert_read_only(sql)
        except NonReadOnlyQueryError as exc:
            record.status, record.error = "rejected", str(exc)
            return _error(record.error)

        con = self._connection()
        timer = threading.Timer(self.timeout_s, con.interrupt)
        started = time.monotonic()
        timer.start()
        try:
            cur = con.execute(self.resolve_files(sql))
            names = [d[0] for d in cur.description or []]
            fetched = cur.fetchmany(self.max_rows + 1)
        except duckdb.InterruptException:
            record.error = f"A query passou de {self.timeout_s:.0f} s e foi interrompida."
            return _error(record.error)
        except duckdb.Error as exc:
            record.error = f"run_sql falhou: {self._tidy(str(exc))}"
            return _error(record.error)
        finally:
            timer.cancel()
            record.elapsed_ms = int((time.monotonic() - started) * 1000)

        rows = [jsonable_row(dict(zip(names, row, strict=True))) for row in fetched]
        record.status = "ok"
        record.row_count = len(rows)
        payload: dict[str, Any] = {
            "query_no": record.query_no,
            "row_count": len(rows[: self.max_rows]),
            "rows": rows[: self.max_rows],
        }
        if len(rows) > self.max_rows:
            payload["truncado"] = f"mais de {self.max_rows} linhas; {self.max_rows} devolvidas."
        return _ok(payload)


def build_csv_server(tools: CsvTools) -> Any:
    """In-process MCP server exposing the arm D tools."""

    @tool("list_files", CSV_TOOL_DESCRIPTIONS["list_files"], {})
    async def list_files_tool(args: dict[str, Any]) -> dict[str, Any]:
        return tools.list_files(args)

    @tool(
        "head_file",
        CSV_TOOL_DESCRIPTIONS["head_file"],
        {
            "arquivo": Annotated[str, "Nome do arquivo"],
            "n": Annotated[int, "Número de linhas, 1 a 50"],
        },
    )
    async def head_file_tool(args: dict[str, Any]) -> dict[str, Any]:
        return tools.head_file(args)

    @tool(
        "run_sql",
        CSV_TOOL_DESCRIPTIONS["run_sql"],
        {"sql": Annotated[str, "Query SQL do DuckDB"]},
    )
    async def run_sql_tool(args: dict[str, Any]) -> dict[str, Any]:
        return tools.sql(args)

    return create_sdk_mcp_server(
        name=CSV_SERVER_NAME,
        version="0.1.0",
        tools=[list_files_tool, head_file_tool, run_sql_tool],
    )
