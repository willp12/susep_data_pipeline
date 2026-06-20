#!/usr/bin/env bash
# 00_preflight.sh — validates GCP credentials and required env vars.
# Idempotent: only reads state, never mutates. Safe to re-run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

log()  { printf '[preflight] %s\n' "$*"; }
err()  { printf '[preflight][ERROR] %s\n' "$*" >&2; }
fail() { err "$*"; exit 1; }

# --- Load .env ---------------------------------------------------------------
if [[ ! -f "${ENV_FILE}" ]]; then
  fail ".env not found at ${ENV_FILE}. Copy .env.example to .env and fill GCP_PROJECT_ID."
fi

# Export only KEY=VALUE lines (ignore comments/blank lines).
set -a
# shellcheck disable=SC1090
source <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "${ENV_FILE}")
set +a

# --- Required env vars -------------------------------------------------------
: "${GCP_PROJECT_ID:?GCP_PROJECT_ID not set in .env}"

if [[ "${GCP_PROJECT_ID}" == *"<preencher"* ]]; then
  fail "GCP_PROJECT_ID still has placeholder value. Edit .env and set a real project ID."
fi

# --- Required CLIs -----------------------------------------------------------
command -v gcloud >/dev/null 2>&1 || fail "gcloud CLI not found on PATH."
command -v bq     >/dev/null 2>&1 || fail "bq CLI not found on PATH (part of gcloud SDK)."

# --- GCP check ---------------------------------------------------------------
log "Checking GCP application-default credentials..."
if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
  fail "gcloud application-default credentials missing. Run: gcloud auth application-default login"
fi

log "Checking GCP project '${GCP_PROJECT_ID}' is accessible..."
if ! gcloud projects describe "${GCP_PROJECT_ID}" >/dev/null 2>&1; then
  fail "Cannot describe GCP project '${GCP_PROJECT_ID}'. Check the ID and your permissions."
fi

# --- Summary + confirmation --------------------------------------------------
cat <<EOF

========================================================================
Preflight summary
------------------------------------------------------------------------
  GCP project       : ${GCP_PROJECT_ID}
  BQ bronze dataset : ${GCP_BQ_DATASET_BRONZE:-susep_ses_bronze}
  BQ staging dataset: ${GCP_BQ_DATASET_STAGING:-susep_ses_staging}
========================================================================

EOF

# Skip prompt if running non-interactively (e.g. from CI) via BOOTSTRAP_ASSUME_YES=1.
if [[ "${BOOTSTRAP_ASSUME_YES:-0}" == "1" ]]; then
  log "BOOTSTRAP_ASSUME_YES=1 — skipping confirmation prompt."
else
  read -r -p "Proceed with this configuration? (y/N) " CONFIRM
  if [[ ! "${CONFIRM}" =~ ^[Yy]$ ]]; then
    fail "Aborted by user."
  fi
fi

log "Preflight OK."
