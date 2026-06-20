# Workload Identity Federation (GitHub Actions → GCP, keyless).
#
# Deferred to Etapa 1c (deliberately out of the first import PR): WIF is the
# fiddliest to no-op (provider attribute-mapping/condition/issuer) and the
# read-only insights workflow depends on it live, so we isolate its blast
# radius. Discovered resources to import here later:
#   - pool:     github-actions-pool   (projects/104419189571/.../workloadIdentityPools/github-actions-pool)
#   - provider: github-provider       (display "GitHub OIDC")
#   - plus the bq-agent-readonly workloadIdentityUser binding.
# NOTE: the pool `github`/provider `fidc-prod` belongs to a DIFFERENT project
# (fidc) — never manage it here.
