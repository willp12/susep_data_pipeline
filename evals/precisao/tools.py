"""As tools do experimento: as funções da produção, isoladas por braço.

Reaproveita ``describe_table``, ``sample_rows`` e ``run_sql`` de
``src.agent.tools`` (com a guarda de somente leitura, o dry-run e o teto de
bytes) e muda só o que vazaria conhecimento ou deixaria um braço sair da sua
camada:

* descrições das tools neutras, as mesmas nos três braços (a da produção manda
  filtrar pelo último ``_ingestion_date``);
* mensagem neutra quando a query passa do teto (a da produção sugere o mesmo
  filtro);
* ``describe_table`` sem as descrições de coluna, para o conhecimento entrar só
  pelo canal do braço;
* allowlist de dataset: cada braço só enxerga a sua camada;
* log por run, em vez do log global do módulo da produção.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Annotated, Any

from claude_agent_sdk import create_sdk_mcp_server, tool
from google.cloud import bigquery

from src.agent.tools import describe_table, run_sql, sample_rows
from src.agent.tools.bq_query import (
    DEFAULT_MAX_BYTES,
    NonReadOnlyQueryError,
    QueryTooExpensiveError,
)

SERVER_NAME = "bq"
MAX_ROWS_RETURNED = 500
_GIB = 1024**3

TOOL_DESCRIPTIONS = {
    "describe_table": "Colunas, tipos e metadados de uma tabela do BigQuery. Sem custo.",
    "sample_rows": "Até n linhas de exemplo de uma tabela (1 a 100). Sem custo.",
    "run_sql": (
        "Executa SQL somente leitura (BigQuery Standard SQL). Um dry-run obrigatório "
        "recusa queries acima de ~1 GiB. Devolve as linhas, os bytes processados e um "
        "query_no."
    ),
}
ALLOWED_TOOLS = [f"mcp__{SERVER_NAME}__{name}" for name in TOOL_DESCRIPTIONS]


@dataclass
class QueryRecord:
    query_no: int
    sql: str
    status: str  # 'ok' | 'rejected' | 'blocked' | 'error'
    bytes_estimated: int | None = None
    bytes_processed: int | None = None
    row_count: int | None = None
    error: str | None = None
    elapsed_ms: int | None = None  # só o braço D mede (DuckDB local)


@dataclass
class ToolLog:
    """Everything one run did through the tools."""

    queries: list[QueryRecord] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)


def _ok(payload: Any) -> dict[str, Any]:
    text = json.dumps(payload, default=str, ensure_ascii=False)
    return {"content": [{"type": "text", "text": text}]}


def _error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "is_error": True}


def cap_message(estimated: int, max_bytes: int) -> str:
    """Over-the-cap message without the production's hint about partitions."""
    return (
        f"A query processaria {estimated / _GIB:.2f} GiB, acima do limite de "
        f"{max_bytes / _GIB:.2f} GiB."
    )


class ArmTools:
    """Handlers of the three tools for one run, confined to one dataset."""

    def __init__(
        self,
        *,
        allowed_dataset: str,
        known_datasets: Collection[str],
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_rows: int = MAX_ROWS_RETURNED,
        client: bigquery.Client | None = None,
    ) -> None:
        self.allowed_dataset = allowed_dataset.lower()
        self.blocked_datasets = sorted({d.lower() for d in known_datasets} - {self.allowed_dataset})
        self.max_bytes = max_bytes
        self.max_rows = max_rows
        self.client = client
        self.log = ToolLog()

    def blocked_reason(self, sql: str) -> str | None:
        """Why ``sql`` reaches outside this arm's dataset, or None if it doesn't."""
        lowered = sql.lower()
        if "region-" in lowered:
            return "Consultas no nível da região ou do projeto não estão disponíveis."
        for dataset in self.blocked_datasets:
            if re.search(rf"(?<![a-z0-9_]){re.escape(dataset)}(?![a-z0-9_])", lowered):
                return (
                    f"O dataset `{dataset}` não está disponível. Use só `{self.allowed_dataset}`."
                )
        return None

    def _dataset_error(self, dataset: str) -> dict[str, Any] | None:
        if dataset.lower() == self.allowed_dataset:
            return None
        return _error(
            f"O dataset `{dataset}` não está disponível. Use só `{self.allowed_dataset}`."
        )

    def describe(self, args: dict[str, Any]) -> dict[str, Any]:
        dataset, table = str(args["dataset"]), str(args["table"])
        self.log.calls.append({"tool": "describe_table", "dataset": dataset, "table": table})
        if denied := self._dataset_error(dataset):
            return denied
        try:
            info = describe_table(dataset, table, client=self.client)
        except Exception as exc:
            return _error(f"describe_table falhou: {exc}")
        info.pop("description", None)
        for column in info.get("columns", []):
            column.pop("description", None)
        return _ok(info)

    def sample(self, args: dict[str, Any]) -> dict[str, Any]:
        dataset, table = str(args["dataset"]), str(args["table"])
        n = int(args.get("n", 5))
        self.log.calls.append({"tool": "sample_rows", "dataset": dataset, "table": table, "n": n})
        if denied := self._dataset_error(dataset):
            return denied
        try:
            return _ok(sample_rows(dataset, table, n, client=self.client))
        except Exception as exc:
            return _error(f"sample_rows falhou: {exc}")

    def sql(self, args: dict[str, Any]) -> dict[str, Any]:
        sql = str(args["sql"])
        record = QueryRecord(query_no=len(self.log.queries) + 1, sql=sql, status="error")
        self.log.queries.append(record)

        if reason := self.blocked_reason(sql):
            record.status, record.error = "blocked", reason
            return _error(reason)
        try:
            result = run_sql(sql, max_bytes=self.max_bytes, client=self.client)
        except QueryTooExpensiveError as exc:
            record.status = "rejected"
            record.bytes_estimated = exc.estimated_bytes
            record.error = cap_message(exc.estimated_bytes, exc.max_bytes)
            return _error(record.error)
        except NonReadOnlyQueryError as exc:
            record.status, record.error = "rejected", str(exc)
            return _error(record.error)
        except Exception as exc:
            record.error = f"run_sql falhou: {exc}"
            return _error(record.error)

        row_count = int(result["row_count"])
        record.status = "ok"
        record.bytes_estimated = int(result["bytes_estimated"])
        record.bytes_processed = int(result["bytes_processed"])
        record.row_count = row_count
        payload: dict[str, Any] = {
            "query_no": record.query_no,
            "row_count": row_count,
            "bytes_processed": record.bytes_processed,
            "rows": result["rows"][: self.max_rows],
        }
        if row_count > self.max_rows:
            payload["truncado"] = f"{row_count} linhas no total, {self.max_rows} devolvidas."
        return _ok(payload)


def build_server(tools: ArmTools) -> Any:
    """In-process MCP server exposing ``tools`` under the production tool names."""

    @tool(
        "describe_table",
        TOOL_DESCRIPTIONS["describe_table"],
        {
            "dataset": Annotated[str, "Dataset"],
            "table": Annotated[str, "Tabela"],
        },
    )
    async def describe_table_tool(args: dict[str, Any]) -> dict[str, Any]:
        return tools.describe(args)

    @tool(
        "sample_rows",
        TOOL_DESCRIPTIONS["sample_rows"],
        {
            "dataset": Annotated[str, "Dataset"],
            "table": Annotated[str, "Tabela"],
            "n": Annotated[int, "Número de linhas, 1 a 100"],
        },
    )
    async def sample_rows_tool(args: dict[str, Any]) -> dict[str, Any]:
        return tools.sample(args)

    @tool(
        "run_sql",
        TOOL_DESCRIPTIONS["run_sql"],
        {"sql": Annotated[str, "Query em BigQuery Standard SQL"]},
    )
    async def run_sql_tool(args: dict[str, Any]) -> dict[str, Any]:
        return tools.sql(args)

    return create_sdk_mcp_server(
        name=SERVER_NAME,
        version="0.1.0",
        tools=[describe_table_tool, sample_rows_tool, run_sql_tool],
    )
