# Inputs. Real values live in terraform.tfvars (gitignored); see the example.
# Defaults mirror the current hand-provisioned infra so a fresh checkout plans
# against reality.

variable "project_id" {
  description = "GCP project hosting the SUSEP SES pipeline."
  type        = string
}

variable "region" {
  description = "Default region for regional resources (none yet; kept for the provider)."
  type        = string
  default     = "us-central1"
}

variable "location" {
  description = "Multi-region for BigQuery datasets and GCS buckets."
  type        = string
  default     = "US"
}

# --- BigQuery datasets (Etapa 1 imports these) ------------------------------
variable "dataset_bronze" {
  description = "Bronze dataset name."
  type        = string
  default     = "susep_ses_bronze"
}

variable "dataset_staging" {
  description = "Staging dataset name (dbt writes here)."
  type        = string
  default     = "susep_ses_staging"
}

variable "dataset_marts" {
  description = "Marts dataset name (dbt writes here; read by the agent/chat)."
  type        = string
  default     = "susep_ses_marts"
}

# --- Buckets ----------------------------------------------------------------
variable "reports_bucket" {
  description = "GCS bucket for agent reports. Empty = derived as <project_id>-susep-ses-reports (see storage.tf)."
  type        = string
  default     = ""
}

variable "data_bucket" {
  description = "GCS bucket for raw + bronze data. Empty = derived as <project_id>-susep-ses-data (see storage.tf)."
  type        = string
  default     = ""
}

# --- Service accounts (Etapa 1 imports these) -------------------------------
variable "agent_sa_account_id" {
  description = "Account id (pre-@) of the read-only insights SA."
  type        = string
  default     = "bq-agent-readonly"
}

variable "ingest_sa_account_id" {
  description = "Account id (pre-@) of the write-capable ingestion SA."
  type        = string
  default     = "susep-ingest"
}
