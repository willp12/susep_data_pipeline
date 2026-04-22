#!/usr/bin/env bash
# 03_gcp_bigquery.sh — creates BigQuery datasets and the ingestion_log table.
#
# Delegates the actual work to `_create_bq_resources.py`, which uses the
# google-cloud-bigquery Python client. We previously used the `bq` CLI here,
# but the version shipped with some gcloud SDK builds has an absl/pyglib
# mismatch that crashes on Windows. The Python client is also a closer match
# to the future Terraform resources (google_bigquery_dataset /
# google_bigquery_table).
#
# Idempotent:
#   - Datasets are created only if absent.
#   - Tables are created only if absent.
#   - NEVER issues DELETE / DROP — schema migrations must be additive and
#     reviewed manually.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

log()  { printf '[bq] %s\n' "$*"; }
fail() { printf '[bq][ERROR] %s\n' "$*" >&2; exit 1; }

[[ -f "${ENV_FILE}" ]] || fail ".env missing. Run 00_preflight.sh first."

set -a
# shellcheck disable=SC1090
source <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "${ENV_FILE}")
set +a

: "${GCP_PROJECT_ID:?GCP_PROJECT_ID not set}"

command -v uv >/dev/null 2>&1 || fail "uv not found on PATH. Run 'make install' first."

log "Delegating to Python (google-cloud-bigquery)..."
cd "${ROOT_DIR}" && uv run python scripts/bootstrap/_create_bq_resources.py
