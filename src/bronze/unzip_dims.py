"""Phase 2: load the SUSEP SES dimension/lookup tables into BigQuery bronze.

The fact table only has codes (`branch_code`, `entity_code`,
`economic_group_code`); the human-readable names live in small lookup CSVs in
the same zip. We land them raw (all STRING, trimmed) in `susep_ses_bronze`;
dbt then builds the clean `dim_*` models and joins names into `fct_seguros`,
so the agent uses real names instead of inferring them.

Source CSVs (confirmed by inspecting the real zip — not guessed):
    Ses_ramos.csv             coramo;noramo
    ses_gruposramos.csv       GRAID;GRANOME;GRACODIGO
    Ses_cias.csv              Coenti;Noenti;Cogrupo;Nogrupo   (group cols empty)
    Ses_grupos_economicos.csv damesano;coenti;noenti;cogrupo;nogrupo

Format is the same as the fact CSV: latin-1, ';'-separated. Some company names
contain stray quote chars, so we disable quote parsing (`quote_char=None`) and
truncate ragged lines. Codes carry trailing spaces → everything is trimmed.
"""

from __future__ import annotations

import io
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import boto3
import polars as pl
import structlog
from google.cloud import bigquery

from src.config import get_settings

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class DimSpec:
    member: str  # CSV name inside the zip
    table: str  # BigQuery bronze table name


DIMS: tuple[DimSpec, ...] = (
    DimSpec("Ses_ramos.csv", "ses_ramos"),
    DimSpec("ses_gruposramos.csv", "ses_gruposramos"),
    DimSpec("Ses_cias.csv", "ses_cias"),
    DimSpec("Ses_grupos_economicos.csv", "ses_grupos_economicos"),
)


def read_dim_csv(raw: bytes) -> pl.DataFrame:
    """Parse a latin-1, ';'-separated lookup CSV into an all-String, trimmed df."""
    text = raw.decode("latin-1")
    df = pl.read_csv(
        io.BytesIO(text.encode("utf-8")),
        separator=";",
        infer_schema=False,  # every column as pl.String
        quote_char=None,  # SUSEP names contain stray quotes
        truncate_ragged_lines=True,
    )
    return df.with_columns(pl.all().str.strip_chars())


def _open_zip(zip_source: str) -> tuple[zipfile.ZipFile, Any]:
    """Open the zip from a local path or an s3:// URI. Returns (zip, cleanup)."""
    if zip_source.startswith("s3://"):
        bucket, key = zip_source[len("s3://") :].split("/", 1)
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        tmp.close()
        log.info("dims.download.start", uri=zip_source)
        boto3.client("s3").download_file(bucket, key, tmp.name)
        log.info("dims.download.ok", uri=zip_source)
        return zipfile.ZipFile(tmp.name), Path(tmp.name)
    return zipfile.ZipFile(zip_source), None


def _load_to_bronze(client: bigquery.Client, df: pl.DataFrame, table_id: str) -> int:
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        autodetect=True,
    )
    with tempfile.TemporaryDirectory(prefix="susep-dims-") as tmpdir:
        parquet = Path(tmpdir) / "dim.parquet"
        df.write_parquet(parquet, compression="snappy")
        with parquet.open("rb") as fh:
            job = client.load_table_from_file(fh, table_id, job_config=job_config)
        job.result()
    return int(df.height)


def load_dims(zip_source: str, *, client: bigquery.Client | None = None) -> dict[str, int]:
    """Load every dimension CSV from the zip into a bronze table. Returns row counts."""
    settings = get_settings()
    if not settings.gcp_project_id:
        raise RuntimeError("GCP_PROJECT_ID not set — populate .env.")
    client = client or bigquery.Client(project=settings.gcp_project_id)

    zf, cleanup = _open_zip(zip_source)
    counts: dict[str, int] = {}
    try:
        names = set(zf.namelist())
        for spec in DIMS:
            if spec.member not in names:
                raise RuntimeError(f"'{spec.member}' not found in zip. Has: {sorted(names)[:30]}")
            df = read_dim_csv(zf.read(spec.member))
            table_id = f"{settings.gcp_project_id}.{settings.gcp_bq_dataset_bronze}.{spec.table}"
            rows = _load_to_bronze(client, df, table_id)
            counts[spec.table] = rows
            log.info("dims.load.ok", table=table_id, rows=rows, cols=df.width)
    finally:
        zf.close()
        if cleanup is not None:
            cleanup.unlink(missing_ok=True)
    return counts


def main() -> int:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )
    if len(sys.argv) != 2:
        print(
            "Usage: python -m src.bronze.unzip_dims <s3://bucket/raw/...zip | /local/path.zip>",
            file=sys.stderr,
        )
        return 2
    try:
        counts = load_dims(sys.argv[1])
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("---")
    for table, rows in counts.items():
        print(f"{table}: {rows} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
