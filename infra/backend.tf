# Remote state in GCS (versioned bucket), namespaced under the susep/ prefix
# since the GCP project hosts unrelated stuff.
#
# Chicken-and-egg: the backend cannot manage the bucket that stores its own
# state, so the bucket is created ONCE, out-of-band — see scripts/create-state-bucket.sh
# (or the README). Backend blocks can't reference variables, hence the literal.
terraform {
  backend "gcs" {
    bucket = "hardy-portal-455916-d3-tf-state"
    prefix = "susep"
  }
}
