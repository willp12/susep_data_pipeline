# Remote state in GCS (versioned bucket), namespaced under the susep/ prefix
# since the GCP project may host unrelated workloads.
#
# Chicken-and-egg: the backend cannot manage the bucket that stores its own
# state, so the bucket is created ONCE, out-of-band — see scripts/create-state-bucket.sh
# (or the README).
#
# The bucket name is environment-specific and backend blocks can't reference
# variables, so it is NOT hardcoded. Provide it at init time via partial config:
#   terraform init -backend-config=backend.hcl
# where backend.hcl (gitignored) contains:  bucket = "<your-project-id>-tf-state"
terraform {
  backend "gcs" {
    prefix = "susep"
  }
}
