#!/usr/bin/env bash
# 03_gcp_bigquery.sh — creates BigQuery datasets and the ingestion_log table.
#
# Idempotent:
#   - Datasets are checked via `bq show` and created only if absent.
#   - Tables are checked the same way.
#   - NEVER issues DELETE / DROP — schema migrations must be additive and
#     reviewed manually.
#
# Written with a future Terraform migration in mind: each create maps cleanly
# to google_bigquery_dataset / google_bigquery_table resources.
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
DATASET_BRONZE="${GCP_BQ_DATASET_BRONZE:-susep_ses_bronze}"
DATASET_STAGING="${GCP_BQ_DATASET_STAGING:-susep_ses_staging}"
LOCATION="${GCP_BQ_LOCATION:-US}"

LOG_TABLE="${GCP_PROJECT_ID}:${DATASET_BRONZE}.ingestion_log"

# --- Dataset helpers ---------------------------------------------------------
dataset_exists() {
  local fq="$1"
  bq --project_id="${GCP_PROJECT_ID}" show --format=prettyjson "${fq}" >/dev/null 2>&1
}

ensure_dataset() {
  local name="$1"
  local fq="${GCP_PROJECT_ID}:${name}"
  if dataset_exists "${fq}"; then
    log "Dataset ${fq} already exists — skipping create."
    return 0
  fi
  log "Creating dataset ${fq} (location=${LOCATION})..."
  bq --project_id="${GCP_PROJECT_ID}" --location="${LOCATION}" mk \
    --dataset \
    --description="susep-ses-pipeline ${name}" \
    --label=project:susep-ses-pipeline \
    --label=env:dev \
    --label=managedby:bootstrap-script \
    "${fq}"
}

ensure_dataset "${DATASET_BRONZE}"
ensure_dataset "${DATASET_STAGING}"

# --- ingestion_log table -----------------------------------------------------
table_exists() {
  bq --project_id="${GCP_PROJECT_ID}" show --format=prettyjson "$1" >/dev/null 2>&1
}

if table_exists "${LOG_TABLE}"; then
  log "Table ${LOG_TABLE} already exists — skipping create (never ALTER/DROP here)."
else
  log "Creating table ${LOG_TABLE}..."
  SCHEMA_JSON="$(mktemp)"
  trap 'rm -f "${SCHEMA_JSON}"' EXIT

  cat > "${SCHEMA_JSON}" <<'EOF'
[
  { "name": "ingestion_date", "type": "DATE",      "mode": "REQUIRED", "description": "UTC date the file was ingested (partition key)." },
  { "name": "file_name",      "type": "STRING",    "mode": "REQUIRED", "description": "Source file name (e.g. ses_seguros.csv)." },
  { "name": "file_hash",      "type": "STRING",    "mode": "REQUIRED", "description": "SHA256 of the raw zip." },
  { "name": "source_url",     "type": "STRING",    "mode": "REQUIRED", "description": "Original download URL scraped from SUSEP." },
  { "name": "status",         "type": "STRING",    "mode": "REQUIRED", "description": "'ingested' | 'no_change' | 'failed'." },
  { "name": "run_timestamp",  "type": "TIMESTAMP", "mode": "REQUIRED", "description": "Pipeline run timestamp." }
]
EOF

  bq --project_id="${GCP_PROJECT_ID}" mk \
    --table \
    --time_partitioning_field=ingestion_date \
    --time_partitioning_type=DAY \
    --clustering_fields=file_name \
    --description="Ingestion log for susep-ses-pipeline (one row per pipeline run)." \
    --label=project:susep-ses-pipeline \
    --label=env:dev \
    --label=managedby:bootstrap-script \
    "${LOG_TABLE}" \
    "${SCHEMA_JSON}"
fi

log "BigQuery resources converged OK."
