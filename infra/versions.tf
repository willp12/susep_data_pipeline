# Terraform + provider version pins.
#
# >= 1.5 is required for `import {}` blocks — Etapa 1 adopts the existing
# (hand-provisioned) GCP resources declaratively, so we never recreate data.
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}
