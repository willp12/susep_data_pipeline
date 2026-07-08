# Task image for the susep_weekly DAG (dags/susep.py) — self-hosted Airflow.
# One image runs both tasks: the ingestion pipeline (`python -m src.main`) and
# the insights agent (`dbt parse` + `python -m src.agent.main`). The
# DockerOperator passes each task's full command, so there is NO ENTRYPOINT/CMD
# here. No Airflow dependency inside the image — ever.
#
# Python 3.12 mirrors the local environment (requires-python >=3.12,<3.13).
# The platform pin matches the amd64 VM: CI already builds on amd64, but a
# manual build+push from an ARM machine must not silently publish an arm64
# :latest that the VM cannot run.
FROM --platform=linux/amd64 python:3.12-slim-bookworm

# uv pinned to the same version that maintains this repo's uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Node 24 + the Claude Code CLI, required by the Agent SDK — mirrors the
# setup-node/npm steps of insights.yml. The NodeSource apt repo is added
# directly (signed-by keyring) instead of piping its setup_24.x script to
# bash, so no unverified remote script runs at build time; the repo pins the
# major (24.x) while still picking up security patches, and the CLI is pinned
# exactly, as in CI.
# ca-certificates is explicit and kept: truststore uses the OS trust store to
# reach the SUSEP site, and GCP/Anthropic/Brevo calls all ride on TLS.
# This layer sits BEFORE the dependency/code layers so editing pyproject.toml
# or src/ never re-downloads Node.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -d -m 0755 /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
       | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_24.x nodistro main" \
       > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code@2.1.201 \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Layer 1 — dependencies only (no project): editing src/ or dbt/ doesn't
# invalidate this cache. --frozen guarantees exactly what's in uv.lock.
# "agent" is a [dependency-groups] group (PEP 735), hence --group agent;
# --no-dev drops the default dev group; the ui group stays out. Ingestion
# doesn't need the agent group (ingest.yml installs core only), but this
# single image serves both tasks, so it goes in.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --group agent --no-install-project

# Layer 2 — the code + project install. hatchling reads readme = "README.md"
# from [project], so the README must be in the build context (it is NOT
# excluded in .dockerignore, unlike everything else).
COPY README.md ./
COPY src/ ./src/
COPY dbt/ ./dbt/
RUN uv sync --frozen --no-dev --group agent

# From here on `uv run` uses the .venv as-is, without re-syncing (otherwise it
# would try to install the dev group — no network at runtime).
# No `dbt deps` bake: this dbt project has no packages.yml.
ENV UV_NO_SYNC=1 \
    PATH="/app/.venv/bin:$PATH"
