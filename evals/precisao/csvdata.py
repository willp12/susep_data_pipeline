"""Prepara os CSVs crus do braço D e confere o gabarito neles.

    uv run python -m evals.precisao.csvdata

1. Acha na ``ingestion_log`` a carga do snapshot do gabarito e o hash do zip.
2. Baixa o zip de ``raw/<data>/`` no bucket de dados e confere o SHA-256.
3. Extrai os CSVs que o braço D lê, intactos, em ``files/``.
4. Calcula as cinco respostas nos CSVs, com as regras aplicadas à mão no
   DuckDB, e exige que batam com o gabarito no centavo. É a terceira derivação,
   depois do mart e da bronze: prova que o zip é o mesmo snapshot.

Encoding: o ``Ses_seguros.csv`` é ASCII puro, mas os cadastros vêm em
Windows-1252, não em latin-1: trazem aspas e travessões tipográficos (bytes
0x92, 0x93, 0x94, 0x96), que o latin-1 do DuckDB recusa. A referência
decodifica Windows-1252 e grava cópias UTF-8 em ``ref/``; o agente do braço D
continua lendo os originais de ``files/``.

Os arquivos ficam em ``evals/precisao/results/csv/<snapshot>/``, fora do git.
Rodar de novo reaproveita o zip e os CSVs já conferidos.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import google.cloud.storage as storage
from google.cloud import bigquery

from evals.precisao.csvtools import CSV_FILES
from evals.precisao.questions import QUESTIONS, render_csv_sql
from evals.precisao.truth import answer_from_rows, differences
from src.config import get_settings
from src.ingestion.hasher import sha256_file

RESULTS_DIR = Path("evals/precisao/results")
CENT = Decimal("0.01")


def snapshot_dir(snapshot: str, root: Path = RESULTS_DIR) -> Path:
    return root / "csv" / snapshot


def csv_dir(snapshot: str, root: Path = RESULTS_DIR) -> Path:
    """Where the arm D files for ``snapshot`` live."""
    return snapshot_dir(snapshot, root) / "files"


def logged_hash(client: bigquery.Client, dataset: str, snapshot: str) -> str:
    """SHA-256 of the zip ingested on ``snapshot``, as the pipeline logged it."""
    job = client.query(
        f"SELECT file_hash FROM `{dataset}.ingestion_log` "  # noqa: S608 -- dataset from settings
        "WHERE ingestion_date = @d AND status = 'ingested' "
        "ORDER BY run_timestamp DESC LIMIT 1",
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("d", "DATE", snapshot)]
        ),
    )
    rows = list(job.result())
    if not rows:
        raise RuntimeError(f"nenhuma carga 'ingested' em {snapshot} na ingestion_log")
    return str(rows[0]["file_hash"])


def fetch_zip(bucket: str, snapshot: str, expected_hash: str, dest: Path) -> Path:
    """Download the snapshot's raw zip (newest first) until one matches the logged hash."""
    target = dest / "BaseCompleta.zip"
    if target.exists() and sha256_file(target) == expected_hash:
        print(f"zip já baixado e conferido: {target}")
        return target
    dest.mkdir(parents=True, exist_ok=True)
    blobs = sorted(
        storage.Client().list_blobs(bucket, prefix=f"raw/{snapshot}/"),
        key=lambda b: b.name,
        reverse=True,
    )
    for blob in blobs:
        print(f"baixando gs://{bucket}/{blob.name} ({blob.size / 1e6:.0f} MB)...", flush=True)
        blob.download_to_filename(str(target))
        if sha256_file(target) == expected_hash:
            print("SHA-256 confere com a ingestion_log.")
            return target
        print("SHA-256 diferente do logado; tentando o próximo.")
    raise RuntimeError(f"nenhum zip em raw/{snapshot}/ tem o hash {expected_hash}")


def extract(zip_path: Path, dest: Path) -> None:
    """Extract the arm D files, matching names case-insensitively."""
    dest.mkdir(parents=True, exist_ok=True)
    wanted = {name.lower(): name for name in CSV_FILES}
    with zipfile.ZipFile(zip_path) as zf:
        found = {}
        for member in zf.namelist():
            base = Path(member).name
            if base.lower() in wanted:
                found[wanted[base.lower()]] = member
        missing = set(CSV_FILES) - set(found)
        if missing:
            raise RuntimeError(f"faltam no zip: {sorted(missing)}")
        for name, member in found.items():
            (dest / name).write_bytes(zf.read(member))
    print(f"{len(CSV_FILES)} CSVs extraídos em {dest}")


def non_ascii_lines(path: Path) -> dict[str, int]:
    """Data lines, and how many carry a byte outside ASCII."""
    lines = path.read_bytes().splitlines()[1:]
    return {
        "linhas": len(lines),
        "com_byte_nao_ascii": sum(1 for line in lines if any(b >= 0x80 for b in line)),
    }


def transcode_reference(files: Path, ref: Path) -> None:
    """Decode each CSV as Windows-1252 (its real encoding) into UTF-8 copies."""
    ref.mkdir(parents=True, exist_ok=True)
    for name in CSV_FILES:
        text = (files / name).read_bytes().decode("cp1252")
        (ref / name).write_text(text, encoding="utf-8", newline="")


def csv_answers(files: Path) -> dict[str, dict[str, Any]]:
    """The five reference answers computed from UTF-8 copies of the CSVs."""
    con = duckdb.connect(":memory:")
    answers = {}
    for question in QUESTIONS:
        cur = con.execute(render_csv_sql(question.csv_sql, files))
        names = [d[0] for d in cur.description or []]
        rows = [dict(zip(names, row, strict=True)) for row in cur.fetchall()]
        answers[question.qid] = answer_from_rows(question, rows)
    con.close()
    return answers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--truth", type=Path, default=RESULTS_DIR / "truth.json")
    args = parser.parse_args()
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    truth = json.loads(args.truth.read_text(encoding="utf-8"))
    snapshot = truth["snapshot"]
    settings = get_settings()
    client = bigquery.Client(project=settings.gcp_project_id)

    expected = logged_hash(client, settings.gcp_bq_dataset_bronze, snapshot)
    zip_path = fetch_zip(settings.gcs_data_bucket, snapshot, expected, snapshot_dir(snapshot))
    files = csv_dir(snapshot)
    if not all((files / name).exists() for name in CSV_FILES):
        extract(zip_path, files)
    ref = snapshot_dir(snapshot) / "ref"
    transcode_reference(files, ref)

    problems: list[str] = []
    answers = csv_answers(ref)
    for qid, answer in answers.items():
        for diff in differences(truth["questions"][qid]["answer"], answer, tolerance=CENT):
            problems.append(f"{qid}: {diff}")
    if problems:
        print("ERRO: os CSVs não batem com o gabarito:\n  " + "\n  ".join(problems))
        return 1

    check = {
        "snapshot": snapshot,
        "zip_sha256": expected,
        "arquivos": {name: (files / name).stat().st_size for name in CSV_FILES},
        # Linhas com byte fora do ASCII: as que ignore_errors descarta ao ler como UTF-8.
        "linhas_nao_ascii": {name: non_ascii_lines(files / name) for name in CSV_FILES},
        "respostas": answers,
    }
    (snapshot_dir(snapshot) / "csv_check.json").write_text(
        json.dumps(check, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"gabarito confere nos CSVs de {snapshot}: mart, bronze e CSV batem no centavo.")
    for qid, answer in answers.items():
        print(f"  {qid}: {answer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
