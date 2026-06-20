#!/usr/bin/env bash
# create-state-bucket.sh — one-time, out-of-band creation of the Terraform
# remote-state bucket. The GCS backend can't manage the bucket that holds its
# own state, so this runs ONCE before the first `terraform init`.
#
# Idempotent: no-ops if the bucket already exists. Versioning is ON so a
# corrupted/concurrent state write can be rolled back.
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-hardy-portal-455916-d3}"
LOCATION="${TF_STATE_LOCATION:-US}"
BUCKET="${TF_STATE_BUCKET:-${PROJECT_ID}-tf-state}"

log() { printf '[tf-state] %s\n' "$*"; }

if gcloud storage buckets describe "gs://${BUCKET}" --format="value(name)" >/dev/null 2>&1; then
  log "Bucket gs://${BUCKET} already exists — nothing to do."
else
  log "Creating gs://${BUCKET} (location ${LOCATION})..."
  gcloud storage buckets create "gs://${BUCKET}" \
    --project="${PROJECT_ID}" \
    --location="${LOCATION}" \
    --uniform-bucket-level-access \
    --public-access-prevention
fi

log "Enabling object versioning on the state bucket..."
gcloud storage buckets update "gs://${BUCKET}" --versioning >/dev/null

log "State bucket ready: gs://${BUCKET}  (backend prefix: susep/)"
log "Next: cd infra && terraform init"
