# Service accounts + IAM — adopted from the live project (Etapa 1).
#
# Imported, not created: a no-op `plan` after import proves we captured reality.
# Scope here: the two SAs and their PROJECT-level roles, plus the reports-bucket
# and dataset grants (in storage.tf / bigquery.tf). WIF impersonation bindings
# are Etapa 1c.

locals {
  agent_sa_email  = "${var.agent_sa_account_id}@${var.project_id}.iam.gserviceaccount.com"
  ingest_sa_email = "${var.ingest_sa_account_id}@${var.project_id}.iam.gserviceaccount.com"
}

# --- Service accounts -------------------------------------------------------
resource "google_service_account" "agent" {
  account_id   = var.agent_sa_account_id
  display_name = "BQ read-only agent (insights)"
}

resource "google_service_account" "ingest" {
  account_id   = var.ingest_sa_account_id
  display_name = "SUSEP SES ingestion (write: BQ load + dbt build)"
}

import {
  to = google_service_account.agent
  id = "projects/${var.project_id}/serviceAccounts/${local.agent_sa_email}"
}

import {
  to = google_service_account.ingest
  id = "projects/${var.project_id}/serviceAccounts/${local.ingest_sa_email}"
}

# --- Project-level roles ----------------------------------------------------
# Read-only insights SA: view data + run jobs.
resource "google_project_iam_member" "agent_data_viewer" {
  project = var.project_id
  role    = "roles/bigquery.dataViewer"
  member  = "serviceAccount:${local.agent_sa_email}"
}

resource "google_project_iam_member" "agent_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${local.agent_sa_email}"
}

# Ingestion SA: run jobs (project) + dataset-level WRITER (see bigquery.tf).
resource "google_project_iam_member" "ingest_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${local.ingest_sa_email}"
}

import {
  to = google_project_iam_member.agent_data_viewer
  id = "${var.project_id} roles/bigquery.dataViewer serviceAccount:${local.agent_sa_email}"
}

import {
  to = google_project_iam_member.agent_job_user
  id = "${var.project_id} roles/bigquery.jobUser serviceAccount:${local.agent_sa_email}"
}

import {
  to = google_project_iam_member.ingest_job_user
  id = "${var.project_id} roles/bigquery.jobUser serviceAccount:${local.ingest_sa_email}"
}
