"""Bronze step: raw zip in GCS → extracted CSV → parquet in GCS bronze/.

For the MVP we only extract **one** CSV from the zip — ``ses_seguros.csv`` —
per the project scope in CLAUDE.md. Other CSVs in the zip are Phase 2.

Encoding + format (confirmed with the owner, not guessed):
    separator = ';'
    encoding  = 'latin-1'
    decimal   = ','   (European; thousand separator varies, rely on polars)

polars 1.40's ``read_csv`` only speaks ``utf8`` / ``utf8-lossy``, so we
stream-transcode latin-1 → utf-8 into a sibling temp file and hand *that* to
polars. Transcoding in Python is ~50-100 MB/s which is fine for a single
300 MB CSV; streaming keeps memory flat.

Output key layout (Hive-style, so downstream BQ external tables / dbt can
partition on it cheaply):

    gs://{bucket}/bronze/ses_seguros/ingestion_date={YYYY-MM-DD}/
        ses_seguros_{YYYYMMDDTHHMMSSZ}.parquet

Two columns added to every row:
    _ingestion_date   DATE    — run date (UTC), matches Hive prefix
    _source_file_name STRING  — "ses_seguros.csv" for now, lets us union
                                Phase-2 CSVs into a single table later

Not in scope here: loading to BigQuery, schema validation, dedup against
existing bronze (re-runs will just add another parquet under the same Hive
prefix — BQ external table reads both, dbt handles dedup).
"""

from __future__ import annotations

import sys
import tempfile
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import structlog

from src.config import get_settings
from src.storage import gcs

log = structlog.get_logger(__name__)

# SUSEP ships the file as "Ses_seguros.csv" (capitalised). CLAUDE.md had it
# lowercase; the real zip we downloaded settles the question.
TARGET_CSV_NAME = "Ses_seguros.csv"
_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def _download_raw_zip(gcs_uri: str, dest: Path) -> None:
    gcs.download_file(gcs_uri, dest)


def _extract_target_csv(zip_path: Path, dest_dir: Path, target: str = TARGET_CSV_NAME) -> Path:
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


def _transcode_latin1_to_utf8(src: Path, dst: Path) -> None:
    """Stream-rewrite a latin-1 CSV as utf-8 so polars can read it."""
    log.info("bronze.transcode.start", src=str(src), dst=str(dst))
    with (
        src.open("r", encoding="latin-1", newline="") as rfh,
        dst.open("w", encoding="utf-8", newline="") as wfh,
    ):
        while True:
            chunk = rfh.read(_CHUNK_SIZE)
            if not chunk:
                break
            wfh.write(chunk)
    log.info("bronze.transcode.ok", bytes=dst.stat().st_size)


def _read_csv(utf8_path: Path) -> pl.DataFrame:
    """Read the SUSEP CSV preserving every column as String.

    Bronze is the raw-ish layer — typing belongs in dbt staging
    (``stg_ses_seguros`` per CLAUDE.md). Reading as String also side-steps
    polars' schema inference on 10k sample rows, which can't see later rows
    that flip an inferred ``i64`` to a float (first run here tripped on
    ``consorciosefundos`` at row >10k with value ``108252392,92``).
    """
    return pl.read_csv(
        utf8_path,
        separator=";",
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


def _build_parquet_key(*, ingestion_date: date, run_ts: datetime) -> str:
    date_part = ingestion_date.isoformat()
    ts_part = run_ts.strftime("%Y%m%dT%H%M%SZ")
    return f"bronze/ses_seguros/ingestion_date={date_part}/ses_seguros_{ts_part}.parquet"


def run_bronze_build(raw_gcs_uri: str) -> dict[str, str | int]:
    """End-to-end bronze build for one raw zip. Returns a summary dict."""
    settings = get_settings()
    run_ts = datetime.now(UTC)
    ingestion_date = run_ts.date()

    with tempfile.TemporaryDirectory(prefix="susep-bronze-") as tmpdir:
        tmp = Path(tmpdir)
        zip_path = tmp / "raw.zip"
        _download_raw_zip(raw_gcs_uri, zip_path)

        latin1_csv = _extract_target_csv(zip_path, tmp)
        utf8_csv = tmp / "ses_seguros.utf8.csv"
        _transcode_latin1_to_utf8(latin1_csv, utf8_csv)

        df = _read_csv(utf8_csv)
        log.info("bronze.read.ok", rows=df.height, cols=df.width)

        df = _add_bronze_columns(
            df, ingestion_date=ingestion_date, source_file_name=TARGET_CSV_NAME
        )

        parquet_name = f"ses_seguros_{run_ts.strftime('%Y%m%dT%H%M%SZ')}.parquet"
        parquet_local = tmp / parquet_name
        df.write_parquet(parquet_local, compression="snappy")
        parquet_bytes = parquet_local.stat().st_size
        log.info(
            "bronze.parquet.write.ok",
            path=str(parquet_local),
            bytes=parquet_bytes,
        )

        key = _build_parquet_key(ingestion_date=ingestion_date, run_ts=run_ts)
        uri = gcs.upload_file(parquet_local, settings.gcs_data_bucket, key)

    return {
        "bronze_gcs_uri": uri,
        "rows": df.height,
        "cols": df.width,
        "parquet_bytes": parquet_bytes,
        "ingestion_date": ingestion_date.isoformat(),
    }


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
            "Usage: python -m src.bronze.unzip_to_parquet gs://bucket/raw/...zip",
            file=sys.stderr,
        )
        return 2
    try:
        result = run_bronze_build(sys.argv[1])
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("---")
    for k, v in result.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
