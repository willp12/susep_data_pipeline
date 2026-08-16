"""susep_weekly — SUSEP SES: scrape -> GCS -> BigQuery -> dbt, then the insights agent.

Source repo: https://github.com/willp12/susep_data_pipeline — this file is
synced to the platform's DAGs bucket (gs://<project>-airflow-dags/dags/
susep_data_pipeline/) and the task image is built from this repo's Dockerfile
by .github/workflows/deploy.yml.

PARALLEL-RUN STATUS: the original GitHub Actions crons stay active (ingest.yml
Mon 12:00 UTC, insights.yml Mon 14:00 UTC). Both schedulers run side by side
until cutover, which is why this DAG runs at 15:00 UTC — 3 h after the GH
ingest, so the two never overlap. At 15:00 run_pipeline short-circuits on the
unchanged SUSEP generation hash (a cheap ~1 min no-op), which is exactly the
desired behaviour while both schedulers coexist.

run_insights defaults OFF (params.insights=False): GH's insights cron still
produces the weekly report — running both would duplicate the report AND the
e-mail. Manual validation runs pass {"insights": true} at trigger time.

CUTOVER: remove `schedule:` from ingest.yml and insights.yml in this repo
(keep workflow_dispatch as a manual fallback), then here: revert the cron to
"0 12 * * 1" and flip the insights Param default to True.

Parity with the workflows, step by step, on the same image:
  run_pipeline  = `uv run python -m src.main` (ingest.yml: scrape -> Tier-1
                  hash pre-check -> download/bronze/load only on change ->
                  dbt build; e-mails the "new period ingested" notice itself)
  insights_gate = ShortCircuitOperator on params.insights (see above); a
                  skipped gate is the expected weekly outcome during the
                  parallel-run, and the run stays green
  run_insights  = `dbt parse` (glossary manifest) then `python -m
                  src.agent.main` (insights.yml: publishes report + SQL
                  appendix + run log to GCS and e-mails the report)
The explicit run_pipeline >> run_insights dependency replaces the fragile
2-hour gap between the two GH crons: the agent runs iff the ingest succeeded.

Auth: ADC from the VM metadata server (SA airflow-vm@) — no key files; the
data-side grants (datasets + buckets) live in this repo's infra/. Secrets
resolve at runtime from Secret Manager via {{ var.value.* }} — never in DAG
code. The report e-mail addresses resolve the same way (report_email_to /
report_email_from, empty fallback): not secrets, but operator PII kept out of
a public repo. While unset, every e-mail step logs+skips (delivery is
best-effort by design) — nothing else in the run is affected.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pendulum
from airflow.providers.docker.operators.docker import DockerOperator
from airflow.providers.standard.operators.python import ShortCircuitOperator
from airflow.sdk import DAG, Param
from docker.types import Mount

PROJECT_ID = os.environ["GCP_PROJECT_ID"]  # injected into the scheduler by the stack

# Local mode: AIRFLOW_LOCAL=1 (set only by the local Docker Desktop stack) flips
# the image to the locally built tag and bind-mounts the host's gcloud ADC into
# the task containers (on the VM, ADC comes from the metadata server instead).
# The variable is absent on the VM and in CI, so cloud behaviour is unchanged.
LOCAL = os.environ.get("AIRFLOW_LOCAL") == "1"
IMAGE = (
    "pipelines/susep_data_pipeline:local"
    if LOCAL
    else f"us-central1-docker.pkg.dev/{PROJECT_ID}/pipelines/susep_data_pipeline:latest"
)

# LOCAL_ADC_HOST_PATH is read only inside the local branch — parsing on the VM
# and in CI never touches it.
LOCAL_MOUNTS = (
    [
        Mount(
            source=os.environ["LOCAL_ADC_HOST_PATH"],
            target="/adc/adc.json",
            type="bind",
            read_only=True,
        )
    ]
    if LOCAL
    else []
)
ADC_ENV = {"GOOGLE_APPLICATION_CREDENTIALS": "/adc/adc.json"} if LOCAL else {}

# Same env as the ingest.yml job (incl. the optional Brevo notice e-mail,
# which src.main skips when unset). ADC comes from the metadata server.
PIPELINE_ENV = {
    "GCP_PROJECT_ID": PROJECT_ID,
    "GCP_BQ_LOCATION": "US",
    "BREVO_API_KEY": "{{ var.value.brevo_api_key }}",
    "REPORT_EMAIL_TO": "{{ var.value.get('report_email_to', '') }}",
    "REPORT_EMAIL_FROM": "{{ var.value.get('report_email_from', '') }}",
    **ADC_ENV,
}

# Same env as the insights.yml job: the subscription OAuth token wins over the
# API key when set (empty = ignored, src/config.py handles the fallback);
# Opus + US$1.25 budget mirrors the CI-only override (local default stays
# sonnet/0.75 for cheap test runs).
INSIGHTS_ENV = {
    "GCP_PROJECT_ID": PROJECT_ID,
    "GCP_BQ_LOCATION": "US",
    "CLAUDE_CODE_OAUTH_TOKEN": "{{ var.value.claude_code_oauth_token }}",
    "ANTHROPIC_API_KEY": "{{ var.value.anthropic_api_key }}",
    "AGENT_MODEL": "opus",
    "AGENT_MAX_BUDGET_USD": "1.25",
    # The agent spawns the Node `claude` CLI, and V8 sizes its default heap
    # from HOST RAM (4 GB), not the container's cgroup cap — bound it so a
    # heap spike hits a clean JS OOM instead of tripping mem_limit as an
    # opaque exit 137 that gets retried twice to no avail.
    "NODE_OPTIONS": "--max-old-space-size=768",
    "BREVO_API_KEY": "{{ var.value.brevo_api_key }}",
    "REPORT_EMAIL_TO": "{{ var.value.get('report_email_to', '') }}",
    "REPORT_EMAIL_FROM": "{{ var.value.get('report_email_from', '') }}",
    **ADC_ENV,
}

COMMON = dict(
    image=IMAGE,
    force_pull=not LOCAL,  # cloud deploy = pushing a new :latest; local images are built in place
    auto_remove="force",  # never leak stopped containers on a 30 GB disk
    mount_tmp_dir=False,  # no host tmp coupling
    mounts=LOCAL_MOUNTS,  # ADC bind in local mode; empty in the cloud
)


def _insights_enabled(params: dict) -> bool:
    """True lets run_insights proceed; False short-circuits (skips) it."""
    return bool(params["insights"])


with DAG(
    dag_id="susep_weekly",
    description="SUSEP SES: scrape -> GCS -> BigQuery -> dbt, then the insights agent.",
    # Parallel-run: 3 h after the GH Actions ingest cron (Mon 12:00 UTC) so
    # the two schedulers never overlap; revert to "0 12 * * 1" at cutover
    # (see docstring).
    schedule="0 15 * * 1",  # Mondays 15:00 UTC (~12:00 BRT)
    start_date=pendulum.datetime(2026, 7, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,  # the ingest writes GCS/BQ and rebuilds the marts — never in parallel
    tags=["pipeline", "susep"],
    # Default False during the parallel-run: GH's insights cron still produces
    # the weekly report — running both would duplicate report + e-mail. Flip
    # the default to True at cutover.
    params={
        "insights": Param(
            False,
            type="boolean",
            description=(
                "Run the insights agent after the ingest. Off by default during "
                "the parallel-run (the GitHub Actions cron still e-mails the "
                "weekly report); pass true on manual validation runs."
            ),
        ),
    },
    default_args={
        "retries": 2,  # absorbs Spot preemption mid-task
        "retry_delay": timedelta(minutes=10),
    },
) as dag:
    # Single task for the whole ingest — download -> GCS -> BQ -> dbt build all
    # happen inside src.main, so no shared volume between containers is needed.
    # 45 min covers the ~500 MB download + full rebuild on a new period; the
    # weekly unchanged-hash no-op finishes in ~1 min.
    run_pipeline = DockerOperator(
        task_id="run_pipeline",
        command="uv run python -m src.main",
        environment=PIPELINE_ENV,
        mem_limit="1g",
        execution_timeout=timedelta(minutes=45),
        **COMMON,
    )

    insights_gate = ShortCircuitOperator(
        task_id="insights_gate",
        python_callable=_insights_enabled,
        # Deterministic in-scheduler check — retrying cannot change its
        # outcome. The default retries=2 exists to absorb Spot preemption,
        # which only threatens the Docker tasks.
        retries=0,
    )

    # Mirrors the two insights.yml steps in one container: build the dbt
    # glossary manifest, then run the agent (publishes to GCS + e-mails the
    # report). The agent is the platform's heaviest consumer (~1 GB peak) —
    # 1500m keeps its mem_limit honest on the 4 GB VM.
    run_insights = DockerOperator(
        task_id="run_insights",
        command=(
            'bash -c "uv run dbt parse --project-dir dbt --profiles-dir dbt '
            '&& uv run python -m src.agent.main"'
        ),
        environment=INSIGHTS_ENV,
        mem_limit="1500m",
        execution_timeout=timedelta(minutes=30),
        **COMMON,
    )

    run_pipeline >> insights_gate >> run_insights
