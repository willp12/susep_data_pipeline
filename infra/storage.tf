# GCS buckets.
#
# - reports bucket: agent outputs (Etapa 1, imported).
# - data bucket: raw zips + bronze parquet, replacing S3 (Etapa 2, created).

# Bucket names derive from the project id (mirrors src/config.py). Override the
# reports_bucket / data_bucket variables only to adopt pre-existing buckets whose
# names don't follow the <project_id>-susep-ses-* convention.
locals {
  reports_bucket = var.reports_bucket != "" ? var.reports_bucket : "${var.project_id}-susep-ses-reports"
  data_bucket    = var.data_bucket != "" ? var.data_bucket : "${var.project_id}-susep-ses-data"
}

resource "google_storage_bucket" "reports" {
  name                        = local.reports_bucket
  location                    = var.location
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  labels = {
    env        = "dev"
    managed_by = "bootstrap-script"
    project    = "susep-ses-pipeline"
  }
}

# Read-only insights SA publishes reports here.
resource "google_storage_bucket_iam_member" "reports_agent" {
  bucket = google_storage_bucket.reports.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${local.agent_sa_email}"
}

import {
  to = google_storage_bucket.reports
  id = local.reports_bucket
}

import {
  to = google_storage_bucket_iam_member.reports_agent
  id = "b/${local.reports_bucket} roles/storage.objectAdmin serviceAccount:${local.agent_sa_email}"
}

# --- Data bucket (Etapa 2) — raw + bronze, replacing S3 -----------------------
# Created (not imported). Lifecycle mirrors the old 01_aws_s3.sh: raw → cooler
# storage after 30d, noncurrent versions pruned (raw 90d, bronze 365d).
resource "google_storage_bucket" "data" {
  name                        = local.data_bucket
  location                    = var.location
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  # raw/: live objects → Nearline after 30 days (rarely re-read once ingested).
  lifecycle_rule {
    condition {
      age            = 30
      matches_prefix = ["raw/"]
      with_state     = "LIVE"
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  # raw/: delete noncurrent versions after 90 days.
  lifecycle_rule {
    condition {
      days_since_noncurrent_time = 90
      matches_prefix             = ["raw/"]
    }
    action {
      type = "Delete"
    }
  }

  # bronze/: delete noncurrent versions after 365 days.
  lifecycle_rule {
    condition {
      days_since_noncurrent_time = 365
      matches_prefix             = ["bronze/"]
    }
    action {
      type = "Delete"
    }
  }

  labels = {
    env        = "dev"
    managed_by = "terraform"
    project    = "susep-ses-pipeline"
  }
}

# The ingestion SA reads/writes raw + bronze objects; BigQuery's load job also
# reads the parquet from gs:// as this SA.
resource "google_storage_bucket_iam_member" "data_ingest" {
  bucket = google_storage_bucket.data.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${local.ingest_sa_email}"
}
