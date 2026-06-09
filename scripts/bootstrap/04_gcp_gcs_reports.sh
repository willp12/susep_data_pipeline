#!/usr/bin/env bash
# 04_gcp_gcs_reports.sh — creates the GCS bucket that stores the agent's reports.
#
# The insights agent publishes its outputs here instead of committing them to
# the repo: analysis markdown under reports/, the SQL appendix under queries/,
# structured run logs under logs/ and a manifest.json index at the root.
#
# Idempotent:
#   - Bucket is created only if absent; if it already exists and is accessible,
#     settings are converged (versioning, public access prevention, labels).
#   - If the name is taken by another account, creation fails with gcloud's
#     409 error — pick another name via GCP_REPORTS_BUCKET in .env.
#   - NEVER deletes anything.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

log()  { printf '[gcs-reports] %s\n' "$*"; }
fail() { printf '[gcs-reports][ERROR] %s\n' "$*" >&2; exit 1; }

[[ -f "${ENV_FILE}" ]] || fail ".env missing. Run 00_preflight.sh first."

set -a
# shellcheck disable=SC1090
source <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "${ENV_FILE}")
set +a

: "${GCP_PROJECT_ID:?GCP_PROJECT_ID not set}"

# Bucket names are global, so the default is prefixed with the project id.
BUCKET="${GCP_REPORTS_BUCKET:-${GCP_PROJECT_ID}-susep-ses-reports}"
LOCATION="${GCP_GCS_LOCATION:-US}"

if gcloud storage buckets describe "gs://${BUCKET}" --format="value(name)" >/dev/null 2>&1; then
  log "Bucket gs://${BUCKET} already exists and is accessible — converging settings."
else
  log "Creating bucket gs://${BUCKET} (location ${LOCATION})..."
  gcloud storage buckets create "gs://${BUCKET}" \
    --project="${GCP_PROJECT_ID}" \
    --location="${LOCATION}" \
    --uniform-bucket-level-access \
    --public-access-prevention
fi

# Converge settings on both paths (create flags above are best-effort; update
# is what makes reruns heal a drifted bucket).
log "Applying versioning, public access prevention and labels..."
gcloud storage buckets update "gs://${BUCKET}" \
  --versioning \
  --public-access-prevention \
  --uniform-bucket-level-access \
  --update-labels=project=susep-ses-pipeline,env=dev,managed_by=bootstrap-script \
  >/dev/null

# The CI agent runs as a service account (WIF). Locally you already have
# owner-ish creds via ADC, so the grant only matters for the workflow.
if [[ -n "${GCP_AGENT_SA:-}" ]]; then
  log "Granting roles/storage.objectAdmin on the bucket to ${GCP_AGENT_SA}..."
  gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
    --member="serviceAccount:${GCP_AGENT_SA}" \
    --role="roles/storage.objectAdmin" \
    >/dev/null
else
  log "GCP_AGENT_SA not set in .env — skipping the IAM grant."
  log "The CI agent needs it. Grant later with:"
  log "  gcloud storage buckets add-iam-policy-binding gs://${BUCKET} \\"
  log "    --member='serviceAccount:<agent-sa-email>' --role='roles/storage.objectAdmin'"
fi

log "Reports bucket OK: gs://${BUCKET}"
