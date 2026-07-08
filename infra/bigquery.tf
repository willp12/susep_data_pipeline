# BigQuery datasets — adopted from the live project (Etapa 1).
#
# Terraform manages the dataset "containers"; the `ingestion_log` TABLE stays
# with the Python bootstrap (_create_bq_resources.py), which converges its
# schema additively alongside the pipeline code (e.g. period/generated_at).
# That keeps the evolving schema next to the code that depends on it and avoids
# the notoriously fiddly no-op import of a BigQuery table schema. dbt likewise
# owns the staging/marts tables within these datasets.
#
# access is ignored on the dataset (BigQuery seeds default project-role ACLs we
# don't want to fight); the one grant we added — WRITER for the ingest SA — is
# managed explicitly via google_bigquery_dataset_iam_member below.

locals {
  datasets = {
    bronze  = var.dataset_bronze
    staging = var.dataset_staging
    marts   = var.dataset_marts
  }
}

resource "google_bigquery_dataset" "this" {
  for_each   = local.datasets
  dataset_id = each.value
  location   = var.location

  lifecycle {
    # access: BigQuery seeds default project-role ACLs we don't manage here
    # (the ingest WRITER grant is the explicit iam_member below).
    # description: cosmetic, set by the Python bootstrap and varies per dataset
    # (marts has none) — don't let TF strip it.
    ignore_changes = [access, description]
  }
}

resource "google_bigquery_dataset_iam_member" "ingest_writer" {
  for_each   = local.datasets
  dataset_id = each.value
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${local.ingest_sa_email}"
}

# Read-only insights SA: dataset-scoped viewer (replaces the old project-wide
# bigquery.dataViewer). New binding — created on apply, no import block.
resource "google_bigquery_dataset_iam_member" "agent_reader" {
  for_each   = local.datasets
  dataset_id = each.value
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${local.agent_sa_email}"
}

# Airflow VM SA (repo willp12/airflow): runs the same pipeline as containers
# (DAG susep_weekly). One SA covers both ingest (write) and insights there —
# the ingest/agent split above remains the CI story; splitting the Airflow
# tasks across SAs via impersonation is documented as future hardening.
resource "google_bigquery_dataset_iam_member" "airflow_writer" {
  for_each   = local.datasets
  dataset_id = each.value
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${local.airflow_sa_email}"
}

import {
  for_each = local.datasets
  to       = google_bigquery_dataset.this[each.key]
  id       = "projects/${var.project_id}/datasets/${each.value}"
}

import {
  for_each = local.datasets
  to       = google_bigquery_dataset_iam_member.ingest_writer[each.key]
  id       = "projects/${var.project_id}/datasets/${each.value} roles/bigquery.dataEditor serviceAccount:${local.ingest_sa_email}"
}
