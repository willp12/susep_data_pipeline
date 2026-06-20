#!/usr/bin/env bash
# 05_gcp_ingest_sa.sh — provisions the write-capable ingestion service account.
#
# The daily insights agent runs as a READ-ONLY SA (bq-agent-readonly). The
# scheduled ingestion WRITES (ingestion_log, bronze ses_seguros, and dbt build
# on staging/marts), so it needs its own identity with write scope. Per the
# auth decision, CI authenticates with a JSON key stored in a GitHub secret
# (GCP_SA_KEY) rather than WIF.
#
# This script creates the SA and grants:
#   - roles/bigquery.jobUser   (project-level — run load/query jobs)
#   - WRITER on bronze/staging/marts datasets (dataset-level dataEditor)
# It then tells you how to mint the JSON key and which secrets to add. S3 write
# is on the AWS side (see aws_ingest_policy.json + the README).
#
# Idempotent: re-running converges (SA created only if absent; grants added
# only if missing). NEVER removes bindings or deletes the SA.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

log()  { printf '[ingest-sa] %s\n' "$*"; }
fail() { printf '[ingest-sa][ERROR] %s\n' "$*" >&2; exit 1; }

[[ -f "${ENV_FILE}" ]] || fail ".env missing. Run 00_preflight.sh first."

set -a
# shellcheck disable=SC1090
source <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "${ENV_FILE}")
set +a

: "${GCP_PROJECT_ID:?GCP_PROJECT_ID not set}"

SA_NAME="${INGEST_SA_NAME:-susep-ingest}"
SA_EMAIL="${SA_NAME}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"

command -v gcloud >/dev/null 2>&1 || fail "gcloud not found on PATH."
command -v uv >/dev/null 2>&1 || fail "uv not found on PATH. Run 'make install' first."

if gcloud iam service-accounts describe "${SA_EMAIL}" --project="${GCP_PROJECT_ID}" \
    >/dev/null 2>&1; then
  log "Service account ${SA_EMAIL} already exists."
else
  log "Creating service account ${SA_EMAIL}..."
  gcloud iam service-accounts create "${SA_NAME}" \
    --project="${GCP_PROJECT_ID}" \
    --display-name="SUSEP SES ingestion (write: BQ load + dbt build)"
fi

log "Granting roles/bigquery.jobUser (project) to ${SA_EMAIL}..."
gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/bigquery.jobUser" \
  --condition=None \
  >/dev/null

log "Granting dataset-level WRITER on bronze/staging/marts..."
cd "${ROOT_DIR}"
INGEST_SA_EMAIL="${SA_EMAIL}" uv run python scripts/bootstrap/_grant_ingest_dataset_access.py

cat <<EOF

[ingest-sa] Service account ready: ${SA_EMAIL}

Next steps (one-time, manual — these mint/secret credentials):

  1. Create a JSON key and add it to the GitHub secret GCP_SA_KEY:
       gcloud iam service-accounts keys create ingest-sa-key.json \\
         --iam-account=${SA_EMAIL} --project=${GCP_PROJECT_ID}
       gh secret set GCP_SA_KEY < ingest-sa-key.json
       rm ingest-sa-key.json     # don't leave the key on disk

  2. Create an AWS IAM user with write on s3://${AWS_S3_BUCKET:-susep-ses-data}
     using scripts/bootstrap/aws_ingest_policy.json, then add its keys:
       gh secret set AWS_ACCESS_KEY_ID
       gh secret set AWS_SECRET_ACCESS_KEY

The ingestion workflow (PR 3) consumes GCP_SA_KEY + the two AWS secrets.
EOF

log "Done."
