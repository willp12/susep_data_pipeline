"""End-to-end orchestration: scrape → raw → bronze → BQ load → dbt build.

This is the MVP entrypoint. Designed for one-shot manual runs — no retry
logic beyond what each step already has, no crash recovery, no partial
re-runs. Each step already produces an auditable artefact (a GCS object or
a BQ row), so a failed run can be resumed by running the downstream steps
against the last successful GCS URI.

Orchestration is deliberately a flat `run()` function rather than a DAG
library — we have five steps in a fixed linear order, and a DAG would just
add a dependency without buying anything.

Short-circuit: if `run_raw_ingest()` returns status='no_change', nothing
downstream needs to run — the last successful load already represents the
current SUSEP data, and re-running bronze/BQ/dbt on the same bytes would
just churn.

dbt is invoked via subprocess (not the programmatic Python API) because
``dbt-core``'s Python interface is not a stable public contract, whereas
the CLI's exit code and stdout are. Env vars are passed through explicitly
so the BQ profile (``profiles.yml``) resolves against the current `.env`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import structlog

from src.agent.emailer import send_ingest_notification
from src.bronze.unzip_to_parquet import run_bronze_build
from src.config import get_settings
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


def run() -> dict[str, str]:
    """Execute the full pipeline once. Returns {status, period}.

    ``status`` is 'no_change' (nothing new on SUSEP — short-circuited) or
    'ingested' (a new dump went through bronze → load → dbt build).
    """
    _configure_logging()
    log.info("main.start")

    raw = run_raw_ingest()
    log.info("main.raw.done", **raw)
    outcome = {"status": raw["status"], "period": raw.get("period", "")}

    if raw["status"] == "no_change":
        log.info("main.short_circuit", reason="SUSEP zip unchanged since last ingest")
        return outcome

    bronze = run_bronze_build(raw["gcs_uri"])
    log.info("main.bronze.done", **bronze)

    bronze_uri = bronze["bronze_gcs_uri"]
    assert isinstance(bronze_uri, str)  # narrow dict[str, str|int] for mypy
    load = run_bronze_load(bronze_uri)
    log.info("main.load.done", **load)

    _run_dbt_build()

    log.info("main.ok")
    return outcome


def _emit_github_output(outcome: dict[str, str]) -> None:
    """Expose the outcome as GitHub Actions step outputs (no-op locally)."""
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if not gh_output:
        return
    with open(gh_output, "a", encoding="utf-8") as fh:
        fh.write(f"status={outcome['status']}\n")
        fh.write(f"period={outcome['period']}\n")


def main() -> int:
    try:
        outcome = run()
    except Exception as exc:
        sys.stderr.write(f"[main] ERROR: {exc}\n")
        return 1

    _emit_github_output(outcome)
    print(f"[main] status={outcome['status']} period={outcome['period']}")

    # A new period just landed: notify by e-mail (skipped when SMTP isn't
    # configured, e.g. local runs). Triggering the insights report is the
    # workflow's job — it needs the Actions API, which main.py shouldn't touch.
    if outcome["status"] == "ingested":
        send_ingest_notification(period=outcome["period"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
