#!/usr/bin/env bash
# 01_aws_s3.sh — creates/updates the raw/bronze S3 bucket with safe defaults.
#
# Idempotent: uses put-bucket-* APIs so re-runs converge the live config to
# the desired state without error. If the bucket already exists in another
# AWS account, the script fails loudly instead of silently trying to mutate.
#
# Written with a future Terraform migration in mind — every configuration
# lives in its own put-bucket-* call that maps 1:1 to an aws_s3_bucket_*
# resource.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

log()  { printf '[s3] %s\n' "$*"; }
warn() { printf '[s3][WARN] %s\n' "$*" >&2; }
err()  { printf '[s3][ERROR] %s\n' "$*" >&2; }
fail() { err "$*"; exit 1; }

# --- Load .env ---------------------------------------------------------------
[[ -f "${ENV_FILE}" ]] || fail ".env missing. Run 00_preflight.sh first."

set -a
# shellcheck disable=SC1090
source <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "${ENV_FILE}")
set +a

: "${AWS_S3_BUCKET:?AWS_S3_BUCKET not set}"
: "${AWS_REGION:?AWS_REGION not set}"

BUCKET="${AWS_S3_BUCKET}"
REGION="${AWS_REGION}"
EXPECTED_ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"

# --- Bucket existence + ownership -------------------------------------------
bucket_exists() {
  aws s3api head-bucket --bucket "${BUCKET}" --expected-bucket-owner "${EXPECTED_ACCOUNT}" >/dev/null 2>&1
}

log "Target bucket: s3://${BUCKET} in ${REGION} (account ${EXPECTED_ACCOUNT})"

if bucket_exists; then
  log "Bucket already exists and belongs to this account — will converge config."
else
  # Distinguish "doesn't exist" from "belongs to another account".
  HEAD_OUT="$(aws s3api head-bucket --bucket "${BUCKET}" 2>&1 || true)"
  if printf '%s' "${HEAD_OUT}" | grep -qi '403'; then
    fail "Bucket '${BUCKET}' exists but belongs to another AWS account. Pick a different AWS_S3_BUCKET or transfer ownership."
  fi

  log "Creating bucket..."
  if [[ "${REGION}" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}" >/dev/null
  else
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}" \
      --create-bucket-configuration "LocationConstraint=${REGION}" >/dev/null
  fi
  log "Bucket created."
fi

# --- Block public access (all 4 flags ON) ------------------------------------
log "Applying public access block..."
aws s3api put-public-access-block --bucket "${BUCKET}" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" \
  >/dev/null

# --- Versioning --------------------------------------------------------------
log "Enabling versioning..."
aws s3api put-bucket-versioning --bucket "${BUCKET}" \
  --versioning-configuration Status=Enabled >/dev/null

# --- Default encryption: SSE-S3 (AES256, free) -------------------------------
log "Applying SSE-S3 default encryption..."
aws s3api put-bucket-encryption --bucket "${BUCKET}" \
  --server-side-encryption-configuration '{
    "Rules": [
      {
        "ApplyServerSideEncryptionByDefault": { "SSEAlgorithm": "AES256" },
        "BucketKeyEnabled": true
      }
    ]
  }' >/dev/null

# --- Lifecycle ---------------------------------------------------------------
# raw/   : transition to Glacier Instant Retrieval after 30d; expire noncurrent versions after 90d.
# bronze/: stays in Standard (noncurrent versions pruned after 365d).
#
# Inline JSON (not file://) for cross-platform: AWS CLI on Windows does not
# interpret POSIX /tmp paths that git-bash resolves.
log "Applying lifecycle configuration..."
aws s3api put-bucket-lifecycle-configuration --bucket "${BUCKET}" \
  --lifecycle-configuration '{
    "Rules": [
      {
        "ID": "raw-transition-and-expire-noncurrent",
        "Status": "Enabled",
        "Filter": { "Prefix": "raw/" },
        "Transitions": [
          { "Days": 30, "StorageClass": "GLACIER_IR" }
        ],
        "NoncurrentVersionExpiration": { "NoncurrentDays": 90 }
      },
      {
        "ID": "bronze-keep-standard",
        "Status": "Enabled",
        "Filter": { "Prefix": "bronze/" },
        "NoncurrentVersionExpiration": { "NoncurrentDays": 365 }
      }
    ]
  }' >/dev/null

# --- Tags --------------------------------------------------------------------
log "Applying bucket tags..."
aws s3api put-bucket-tagging --bucket "${BUCKET}" --tagging '{
  "TagSet": [
    { "Key": "Project",   "Value": "susep-ses-pipeline" },
    { "Key": "Env",       "Value": "dev" },
    { "Key": "ManagedBy", "Value": "bootstrap-script" }
  ]
}' >/dev/null

log "Bucket s3://${BUCKET} converged OK."
