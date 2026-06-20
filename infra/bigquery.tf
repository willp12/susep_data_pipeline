# BigQuery datasets + ingestion_log table.
#
# Etapa 1: adopt the existing resources with `import {}` blocks, e.g.
#
#   import {
#     to = google_bigquery_dataset.bronze
#     id = "projects/${var.project_id}/datasets/${var.dataset_bronze}"
#   }
#   resource "google_bigquery_dataset" "bronze" { ... }
#
# Goal: `terraform plan` is a no-op after import (never recreate — the tables
# hold ~1.8M rows). Resources land here in Etapa 1.
