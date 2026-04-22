"""Bronze step: local raw zip → extracted CSV → parquet in S3 bronze/.

The zip is downloaded **once** by the caller (``src/main.py``) to a shared
tempdir and handed to us as a local ``Path``. Earlier this function pulled
the zip from S3 itself, which wasted ~560 MB of egress per CSV in the
Fase 2 loop over ``REGISTRY``. One download, N extractions.

What this function does (per CSV):

1. Extract the target CSV out of the local zip (``spec.csv_name``,
   case-sensitive — SUSEP ships mixed-case filenames).
2. Stream-transcode the CSV from ``spec.encoding`` (usually latin-1) to
   utf-8 so polars 1.40 can read it (polars only accepts utf8 / utf8-lossy).
3. Read it as all-``pl.String`` (no schema inference — the European decimal
   comma + mixed types across rows would trip polars' 10k-row sampler;
   casts belong in dbt staging anyway).
4. Apply the lenient schema contract (see ``src.ingestion.schema_contract``)
   — missing columns become null, extras fold into ``_extras`` JSON.
5. Stamp provenance columns and write a snappy parquet to
   ``s3://{bucket}/bronze/{spec.table_name}/ingestion_date={date}/
   {spec.table_name}_{YYYYMMDDTHHMMSSZ}.parquet``.

Final column order written to parquet:
``list(spec.expected_columns) + [_ingestion_date, _source_file_name, _extras]``.
Stable across runs and across CSV specs so downstream BQ loads / dbt models
don't care whether SUSEP dropped or renamed a column this month.
"""

from __future__ import annotations

import sys
import tempfile
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import boto3
import polars as pl
import structlog

from src.config import get_settings
from src.csv_registry import CsvSpec, get_spec
from src.ingestion.schema_contract import apply_schema_contract

log = structlog.get_logger(__name__)

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def _extract_target_csv(zip_path: Path, dest_dir: Path, target: str) -> Path:
    """Extract a single named CSV. Fails loud with the zip's contents listed."""
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if target not in names:
            preview = names[:25]
            more = f" (+{len(names) - 25} more)" if len(names) > 25 else ""
            raise RuntimeError(
                f"'{target}' not found in {zip_path.name}. "
                f"Zip contents ({len(names)} entries): {preview}{more}"
            )
        out = dest_dir / target
        with zf.open(target) as src, out.open("wb") as dst_fh:
            while True:
                chunk = src.read(_CHUNK_SIZE)
                if not chunk:
                    break
                dst_fh.write(chunk)
    log.info(
        "bronze.extract.ok",
        file=target,
        path=str(out),
        bytes=out.stat().st_size,
    )
    return out


def _transcode_to_utf8(src: Path, dst: Path, *, encoding: str) -> None:
    """Stream-rewrite ``src`` (read as ``encoding``) as utf-8 into ``dst``."""
    log.info(
        "bronze.transcode.start",
        src=str(src),
        dst=str(dst),
        encoding=encoding,
    )
    with (
        src.open("r", encoding=encoding, newline="") as rfh,
        dst.open("w", encoding="utf-8", newline="") as wfh,
    ):
        while True:
            chunk = rfh.read(_CHUNK_SIZE)
            if not chunk:
                break
            wfh.write(chunk)
    log.info("bronze.transcode.ok", bytes=dst.stat().st_size)


def _read_csv(utf8_path: Path, *, separator: str) -> pl.DataFrame:
    """Read the CSV preserving every column as String.

    Bronze is the raw-ish layer — typing belongs in dbt staging. Reading as
    String also side-steps polars' schema inference on 10k sample rows,
    which can't see later rows that flip an inferred ``i64`` to a float
    (the first ``Ses_seguros`` run tripped on ``consorciosefundos`` at
    row >10k with value ``108252392,92``).
    """
    return pl.read_csv(
        utf8_path,
        separator=separator,
        infer_schema=False,  # read every column as pl.String
        try_parse_dates=False,
    )


def _add_bronze_columns(
    df: pl.DataFrame, *, ingestion_date: date, source_file_name: str
) -> pl.DataFrame:
    """Stamp every row with partition + provenance columns."""
    return df.with_columns(
        pl.lit(ingestion_date).cast(pl.Date).alias("_ingestion_date"),
        pl.lit(source_file_name).cast(pl.String).alias("_source_file_name"),
    )


def _build_parquet_key(*, table_name: str, ingestion_date: date, run_ts: datetime) -> str:
    date_part = ingestion_date.isoformat()
    ts_part = run_ts.strftime("%Y%m%dT%H%M%SZ")
    return f"bronze/{table_name}/ingestion_date={date_part}/{table_name}_{ts_part}.parquet"


def _upload_parquet(local_path: Path, bucket: str, key: str) -> str:
    uri = f"s3://{bucket}/{key}"
    log.info("bronze.parquet.upload.start", uri=uri, local=str(local_path))
    boto3.client("s3").upload_file(str(local_path), bucket, key)
    log.info("bronze.parquet.upload.ok", uri=uri)
    return uri


def run_bronze_build(local_zip_path: Path, spec: CsvSpec) -> dict[str, str | int]:
    """Extract one CSV from a local zip, shape it, write parquet to S3.

    ``local_zip_path`` must already be on disk — see module docstring. The
    caller (``main.py``) is responsible for fetching the zip once per run.
    Returns a summary dict suitable for logging + downstream chaining.
    """
    settings = get_settings()
    run_ts = datetime.now(UTC)
    ingestion_date = run_ts.date()

    with tempfile.TemporaryDirectory(prefix=f"susep-bronze-{spec.table_name}-") as tmpdir:
        tmp = Path(tmpdir)

        raw_csv = _extract_target_csv(local_zip_path, tmp, spec.csv_name)
        utf8_csv = tmp / f"{spec.table_name}.utf8.csv"
        _transcode_to_utf8(raw_csv, utf8_csv, encoding=spec.encoding)

        df = _read_csv(utf8_csv, separator=spec.separator)
        log.info(
            "bronze.read.ok",
            spec=spec.table_name,
            rows=df.height,
            cols=df.width,
        )

        # Lenient schema reshape — missing -> null, extras -> _extras JSON.
        df = apply_schema_contract(df, spec)

        # Provenance columns are stamped AFTER the contract so they don't
        # risk colliding with a (hypothetical) expected column named the
        # same thing. Final column order is locked here.
        df = _add_bronze_columns(df, ingestion_date=ingestion_date, source_file_name=spec.csv_name)
        final_order = [
            *spec.expected_columns,
            "_ingestion_date",
            "_source_file_name",
            "_extras",
        ]
        df = df.select(final_order)

        parquet_name = f"{spec.table_name}_{run_ts.strftime('%Y%m%dT%H%M%SZ')}.parquet"
        parquet_local = tmp / parquet_name
        df.write_parquet(parquet_local, compression="snappy")
        parquet_bytes = parquet_local.stat().st_size
        log.info(
            "bronze.parquet.write.ok",
            spec=spec.table_name,
            path=str(parquet_local),
            bytes=parquet_bytes,
        )

        key = _build_parquet_key(
            table_name=spec.table_name,
            ingestion_date=ingestion_date,
            run_ts=run_ts,
        )
        uri = _upload_parquet(parquet_local, settings.aws_s3_bucket, key)

    return {
        "spec": spec.table_name,
        "bronze_s3_uri": uri,
        "rows": df.height,
        "cols": df.width,
        "parquet_bytes": parquet_bytes,
        "ingestion_date": ingestion_date.isoformat(),
    }


def main() -> int:
    """CLI smoke test: ``python -m src.bronze.unzip_to_parquet <zip> <table>``."""
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )
    if len(sys.argv) != 3:
        print(
            "Usage: python -m src.bronze.unzip_to_parquet <local_zip_path> <table_name>",
            file=sys.stderr,
        )
        return 2
    try:
        spec = get_spec(sys.argv[2])
        result = run_bronze_build(Path(sys.argv[1]), spec)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("---")
    for k, v in result.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
