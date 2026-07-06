# Workload Identity Federation (GitHub Actions → GCP, keyless) — Etapa 1c.
#
# Backs the GCP_WIF_PROVIDER secret used by the read-only insights workflow:
# GitHub OIDC tokens from this repo impersonate the bq-agent-readonly SA.
# Imported, not created — a no-op plan proves we captured the live config.
#
# NOTE: a separate workload in this shared project owns its own WIF pool/provider;
# it is intentionally NOT managed here.

data "google_project" "this" {}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-actions-pool"
  display_name              = "GitHub Actions"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name                       = "GitHub OIDC"

  # Restrict token minting to this repo AND the main branch: scheduled runs and
  # workflow_dispatch both execute on main, so no other ref needs GCP access.
  attribute_condition = "assertion.repository == 'willp12/susep_data_pipeline' && assertion.ref == 'refs/heads/main'"

  attribute_mapping = {
    "attribute.ref"        = "assertion.ref"
    "attribute.repository" = "assertion.repository"
    "google.subject"       = "assertion.sub"
  }

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# Lets GitHub OIDC from this repo impersonate the read-only insights SA.
resource "google_service_account_iam_member" "agent_wif" {
  service_account_id = google_service_account.agent.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/projects/${data.google_project.this.number}/locations/global/workloadIdentityPools/github-actions-pool/attribute.repository/willp12/susep_data_pipeline"
}

import {
  to = google_iam_workload_identity_pool.github
  id = "projects/${var.project_id}/locations/global/workloadIdentityPools/github-actions-pool"
}

import {
  to = google_iam_workload_identity_pool_provider.github
  id = "projects/${var.project_id}/locations/global/workloadIdentityPools/github-actions-pool/providers/github-provider"
}

import {
  to = google_service_account_iam_member.agent_wif
  id = "projects/${var.project_id}/serviceAccounts/${local.agent_sa_email} roles/iam.workloadIdentityUser principalSet://iam.googleapis.com/projects/${data.google_project.this.number}/locations/global/workloadIdentityPools/github-actions-pool/attribute.repository/willp12/susep_data_pipeline"
}
