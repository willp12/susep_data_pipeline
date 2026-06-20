# Workload Identity Federation (GitHub Actions → GCP, keyless).
#
# Etapa 1: import the existing pool + provider backing the GCP_WIF_PROVIDER
# secret (used by the read-only insights workflow).
# Etapa 3 (optional): bind the ingest SA to WIF too, retiring the long-lived
# GCP_SA_KEY.
#
# Resources land here in Etapa 1.
