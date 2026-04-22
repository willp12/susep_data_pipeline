"""End-to-end orchestration: scrape → raw → bronze loop → BQ loads → dbt build.

This is the manual-run entrypoint. Designed for one-shot runs — no retry
logic beyond what each step already has, no crash recovery, no partial
re-runs. Each step produces an auditable artefact (an S3 object or a BQ
row), so a failed run can be resumed by running the downstream steps
against the last successful S3 URI.

Shape of a run:

1. ``run_raw_ingest()`` — scrape + download + hash + S3 upload (once per run).
   Short-circuits with ``status='no_change'`` if SUSEP's zip hash matches
   the last successful ingest; nothing downstream needs to run.
2. Download the raw zip **once** to a shared tempdir. Bronze used to fetch
   it from S3 itself, which wasted ~560 MB of egress per CSV now that
   Fase 2 loops over multiple specs.
3. For each :class:`CsvSpec` in :data:`REGISTRY`: extract that CSV from the
   zip, reshape via the schema contract, write a parquet to S3 bronze, load
   to BigQuery with the load strategy the spec declares.
4. ``dbt build`` over the whole staging layer once the bronze tables are
   caught up.

Fail-fast on loop errors: if one spec blows up, we re-raise and leave the
earlier specs loaded. Re-running ``main()`` is the recovery path — raw
ingest short-circuits on hash match, and bronze/load are idempotent by
construction (delete-then-append or truncate-replace). The only manual
step is deleting the ``ingestion_log`` row for the current hash if you
need to bypass the ``no_change`` short-circuit.

dbt is invoked via subprocess (not the programmatic Python API) because
``dbt-core``'s Python interface is not a stable public contract, whereas
the CLI's exit code and stdout are. Env vars are passed through explicitly
so the BQ profile (``profiles.yml``) resolves against the current ``.env``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import boto3
import structlog

from src.bronze.unzip_to_parquet import run_bronze_build
from src.config import get_settings
from src.csv_registry import REGISTRY
from src.ingestion.downloader import run_raw_ingest
from src.loaders.bq_loader import run_bronze_load

log = structlog.get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DBT_DIR = _REPO_ROOT / "dbt"


def _configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"Not an s3:// URI: {uri}")
    bucket, _, key = uri[len("s3://") :].partition("/")
    if not bucket or not key:
        raise ValueError(f"Malformed s3:// URI: {uri}")
    return bucket, key


def _download_raw_zip(s3_uri: str, dest: Path) -> None:
    """S3 → local tempdir, once per run. Bronze loop reuses this file."""
    bucket, key = _parse_s3_uri(s3_uri)
    log.info("main.raw.download.start", uri=s3_uri, dest=str(dest))
    boto3.client("s3").download_file(bucket, key, str(dest))
    log.info("main.raw.download.ok", uri=s3_uri, bytes=dest.stat().st_size)


def _run_dbt_build() -> None:
    """Invoke ``dbt build`` as a subprocess with the repo-local profile."""
    settings = get_settings()
    env = {
        **os.environ,
        "GCP_PROJECT_ID": settings.gcp_project_id,
        "GCP_BQ_DATASET_BRONZE": settings.gcp_bq_dataset_bronze,
        "GCP_BQ_DATASET_STAGING": settings.gcp_bq_dataset_staging,
    }
    cmd = [
        "uv",
        "run",
        "dbt",
        "build",
        "--project-dir",
        str(_DBT_DIR),
        "--profiles-dir",
        str(_DBT_DIR),
    ]
    log.info("main.dbt.build.start", cmd=" ".join(cmd))
    result = subprocess.run(cmd, env=env, cwd=_REPO_ROOT, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(f"dbt build failed with exit code {result.returncode}")
    log.info("main.dbt.build.ok")


def run() -> int:
    """Execute the full pipeline once. Returns a process exit code."""
    _configure_logging()
    log.info("main.start", specs=[s.table_name for s in REGISTRY])

    raw = run_raw_ingest()
    log.info("main.raw.done", **raw)

    if raw["status"] == "no_change":
        log.info(
            "main.short_circuit",
            reason="SUSEP zip hash unchanged since last ingest",
        )
        return 0

    raw_uri = raw["s3_uri"]
    assert isinstance(raw_uri, str)  # narrow for mypy

    with tempfile.TemporaryDirectory(prefix="susep-main-") as tmpdir:
        local_zip = Path(tmpdir) / "raw.zip"
        _download_raw_zip(raw_uri, local_zip)

        for spec in REGISTRY:
            try:
                bronze = run_bronze_build(local_zip, spec)
                log.info("main.bronze.done", **bronze)

                bronze_uri = bronze["bronze_s3_uri"]
                assert isinstance(bronze_uri, str)  # narrow dict[str, str|int]
                load = run_bronze_load(bronze_uri, spec)
                log.info("main.load.done", **load)
            except Exception:
                # Fail-fast: log which spec blew up, then re-raise. Any
                # already-loaded specs stay in BQ; re-running main() resumes
                # via raw's hash-dedupe short-circuit. See module docstring.
                log.error(
                    "main.spec.failed",
                    spec=spec.table_name,
                    exc_info=True,
                )
                raise

    _run_dbt_build()

    log.info("main.ok")
    return 0


def main() -> int:
    try:
        return run()
    except Exception as exc:
        sys.stderr.write(f"[main] ERROR: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
