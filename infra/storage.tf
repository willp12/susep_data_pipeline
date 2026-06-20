# GCS buckets — adopted from the live project (Etapa 1).
#
# The reports bucket (agent outputs). The data bucket that replaces S3 for raw
# + bronze is Etapa 2.

resource "google_storage_bucket" "reports" {
  name                        = var.reports_bucket
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
  id = var.reports_bucket
}

import {
  to = google_storage_bucket_iam_member.reports_agent
  id = "b/${var.reports_bucket} roles/storage.objectAdmin serviceAccount:${local.agent_sa_email}"
}
