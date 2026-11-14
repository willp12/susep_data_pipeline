"""Gabarito: roda os dois SQLs de referência de cada pergunta e exige que batam.

    uv run python -m evals.precisao.truth --out evals/precisao/results/truth.json

Mart e bronze são caminhos independentes para a mesma resposta. Se não baterem
no centavo, o script para sem gravar nada: ou o mart está desatualizado em
relação à bronze, ou há um bug, e as duas coisas precisam ser vistas antes de
gastar com o agente.

Também grava, para contar a história e rotular erros, quanto dariam os dois
atalhos ingênuos mais comuns na pergunta 1: somar todos os snapshots e
converter o valor sem trocar a vírgula.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from google.cloud import bigquery

from evals.precisao.questions import QUESTIONS, Question, render_sql
from evals.precisao.score import normalize_name
from src.config import get_settings

_DIAG_ALL_SNAPSHOTS = """
SELECT SUM(SAFE_CAST(REPLACE(premio_direto, ',', '.') AS NUMERIC)) AS valor
FROM `{bronze}.ses_seguros`
WHERE damesano BETWEEN '202401' AND '202412'
"""

_DIAG_NO_REPLACE = """
SELECT SUM(SAFE_CAST(premio_direto AS NUMERIC)) AS valor
FROM `{bronze}.ses_seguros`
WHERE _ingestion_date = (SELECT MAX(_ingestion_date) FROM `{bronze}.ses_seguros`)
  AND damesano BETWEEN '202401' AND '202412'
"""


def _run(client: bigquery.Client, sql: str) -> tuple[list[dict[str, Any]], int]:
    job = client.query(sql, job_config=bigquery.QueryJobConfig(use_query_cache=False))
    rows = [dict(row) for row in job.result()]
    return rows, int(job.total_bytes_processed or 0)


def answer_from_rows(question: Question, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Normalize reference-query rows into the answer shape score.py compares."""
    if question.kind == "valor":
        return {"valor": str(rows[0]["valor"])}
    if question.kind == "mes_valor":
        return {"mes": rows[0]["mes"], "valor": str(rows[0]["valor"])}
    if question.kind == "ranking":
        return {
            "ranking": [
                {"codigo": r["codigo"], "nome": r["nome"], "valor": str(r["valor"])} for r in rows
            ]
        }
    v2023 = Decimal(rows[0]["v2023"])
    v2024 = Decimal(rows[0]["v2024"])
    return {
        "percentual": str((v2024 / v2023 - 1) * 100),
        "v2023": str(v2023),
        "v2024": str(v2024),
    }


def differences(
    mart: dict[str, Any], other: dict[str, Any], *, tolerance: Decimal = Decimal(0)
) -> list[str]:
    """What differs between two reference answers; empty when they agree.

    ``tolerance`` is the largest absolute gap accepted in a value (0 = exact).
    """

    def close(a: Any, b: Any) -> bool:
        return b is not None and abs(Decimal(a) - Decimal(b)) <= tolerance

    diffs: list[str] = []
    for key in ("valor", "mes", "percentual", "v2023", "v2024"):
        if key not in mart:
            continue
        a, b = mart[key], other.get(key)
        if not (a == b if key == "mes" else close(a, b)):
            diffs.append(f"{key}: mart={a} outro={b}")
    if "ranking" in mart:
        for i, (m, o) in enumerate(zip(mart["ranking"], other["ranking"], strict=False), 1):
            if m["codigo"].strip() != o["codigo"].strip():
                diffs.append(f"ranking {i}: código mart={m['codigo']} outro={o['codigo']}")
            if not close(m["valor"], o["valor"]):
                diffs.append(f"ranking {i}: valor mart={m['valor']} outro={o['valor']}")
            if normalize_name(m["nome"] or "") != normalize_name(o["nome"] or ""):
                diffs.append(f"ranking {i}: nome mart={m['nome']!r} outro={o['nome']!r}")
        if len(mart["ranking"]) != len(other["ranking"]):
            diffs.append("ranking: tamanhos diferentes")
    return diffs


def build_truth(
    client: bigquery.Client, *, project: str, bronze: str, marts: str
) -> dict[str, Any]:
    partitions = sorted(
        p for p in client.list_partitions(f"{project}.{bronze}.ses_seguros") if p.isdigit()
    )
    questions: dict[str, Any] = {}
    problems: list[str] = []

    for question in QUESTIONS:
        mart_rows, mart_bytes = _run(
            client, render_sql(question.mart_sql, bronze=bronze, marts=marts)
        )
        bronze_rows, bronze_bytes = _run(
            client, render_sql(question.bronze_sql, bronze=bronze, marts=marts)
        )
        mart_answer = answer_from_rows(question, mart_rows)
        bronze_answer = answer_from_rows(question, bronze_rows)
        for diff in differences(mart_answer, bronze_answer):
            problems.append(f"{question.qid}: {diff}")
        questions[question.qid] = {
            "kind": question.kind,
            "text": question.text,
            "trap": question.trap,
            "answer": mart_answer,
            "bytes": {"mart": mart_bytes, "bronze": bronze_bytes},
        }

    if problems:
        raise RuntimeError("mart e bronze não batem:\n  " + "\n  ".join(problems))

    all_rows, all_bytes = _run(client, render_sql(_DIAG_ALL_SNAPSHOTS, bronze=bronze, marts=marts))
    raw_rows, _ = _run(client, render_sql(_DIAG_NO_REPLACE, bronze=bronze, marts=marts))
    q1 = Decimal(questions["q1"]["answer"]["valor"])
    all_snapshots = Decimal(all_rows[0]["valor"])
    no_replace = Decimal(raw_rows[0]["valor"] or 0)

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "snapshot": f"{partitions[-1][:4]}-{partitions[-1][4:6]}-{partitions[-1][6:]}",
        "snapshots_k": len(partitions),
        "questions": questions,
        "diagnostics": {
            "q1_todos_snapshots": str(all_snapshots),
            "q1_todos_snapshots_razao": float(all_snapshots / q1),
            "q1_todos_snapshots_bytes": all_bytes,
            "q1_sem_trocar_virgula": str(no_replace),
            "q1_sem_trocar_virgula_razao": float(no_replace / q1),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("evals/precisao/results/truth.json"))
    args = parser.parse_args()
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    settings = get_settings()
    if not settings.gcp_project_id:
        print("ERRO: GCP_PROJECT_ID não definido no .env", file=sys.stderr)
        return 1
    client = bigquery.Client(project=settings.gcp_project_id)
    try:
        truth = build_truth(
            client,
            project=settings.gcp_project_id,
            bronze=settings.gcp_bq_dataset_bronze,
            marts=settings.gcp_bq_dataset_marts,
        )
    except RuntimeError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"gabarito gravado em {args.out}")
    print(f"snapshot {truth['snapshot']}, {truth['snapshots_k']} snapshots na bronze")
    for qid, item in truth["questions"].items():
        print(f"  {qid}: {item['answer']}")
    diag = truth["diagnostics"]
    print(f"  q1 somando todos os snapshots: {diag['q1_todos_snapshots_razao']:.2f}x o certo")
    print(f"  q1 sem trocar a vírgula: {diag['q1_sem_trocar_virgula_razao']:.2%} do certo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
