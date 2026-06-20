# Service accounts + IAM.
#
# Etapa 1: import the two SAs and their bindings —
#   - bq-agent-readonly: BQ dataViewer/jobUser (insights, read-only) + WIF user
#   - susep-ingest: BQ jobUser (project) + dataset WRITER on bronze/staging/marts
# Keep least privilege exactly as provisioned; import, don't widen.
#
# Resources land here in Etapa 1.
