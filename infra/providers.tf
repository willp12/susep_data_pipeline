# Google provider. Authentication is Application Default Credentials:
#   - locally:  gcloud auth application-default login
#   - in CI:    the GCP_SA_KEY service-account key (Etapa 3 may switch to WIF)
# No credentials are ever written to these files.
provider "google" {
  project = var.project_id
  region  = var.region
}
