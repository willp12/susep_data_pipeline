#!/usr/bin/env bash
# 02_gcp_apis.sh — enables the GCP APIs the pipeline depends on.
#
# Idempotent: `gcloud services enable` no-ops on already-enabled APIs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

log()  { printf '[gcp-apis] %s\n' "$*"; }
fail() { printf '[gcp-apis][ERROR] %s\n' "$*" >&2; exit 1; }

[[ -f "${ENV_FILE}" ]] || fail ".env missing. Run 00_preflight.sh first."

set -a
# shellcheck disable=SC1090
source <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "${ENV_FILE}")
set +a

: "${GCP_PROJECT_ID:?GCP_PROJECT_ID not set}"

APIS=(
  "bigquery.googleapis.com"
  "storage.googleapis.com"
)

log "Enabling APIs on project '${GCP_PROJECT_ID}':"
for api in "${APIS[@]}"; do
  printf '  - %s\n' "${api}"
done

gcloud services enable --project="${GCP_PROJECT_ID}" "${APIS[@]}"

log "APIs enabled OK."
