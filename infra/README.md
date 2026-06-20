# infra/ — Terraform

Infrastructure as code for the SUSEP SES pipeline (GCP). This replaces the
imperative `scripts/bootstrap/*.sh` over a staged migration — see the
[roadmap](#roadmap) below. As of Etapa 1, the core GCP resources (datasets,
service accounts, IAM, reports bucket) are adopted into Terraform via
`import {}` blocks with a verified no-op `plan` (nothing recreated). WIF
(Etapa 1c) and the S3→GCS data move (Etapa 2) are still pending.

## First-time setup

```bash
# 1) One-time: create the remote-state bucket (out-of-band — see backend.tf).
bash infra/scripts/create-state-bucket.sh

# 2) Auth (Application Default Credentials) and init the backend.
gcloud auth application-default login        # if not already
cd infra
cp terraform.tfvars.example terraform.tfvars # adjust if needed
terraform init                               # connects to the gcs backend
terraform plan                               # Etapa 0: "No changes."
```

## Auth model

ADC everywhere — no credentials in these files. Locally: your gcloud ADC. In
CI: the `GCP_SA_KEY` service-account key (Etapa 3 may move this to WIF).

## Critical rule — import, never recreate

The infra already exists and holds data (BigQuery tables with ~1.8M rows, the
reports bucket with backfilled reports). Etapa 1 onward MUST adopt resources
with `import {}` blocks and confirm a **no-op `plan`** before any `apply`.
Never let Terraform destroy-and-recreate a stateful resource.

## Roadmap

| Etapa | Escopo | Estado |
| ----- | ------ | ------ |
| 0 | Scaffold: `versions`/`backend`/`providers`/`variables` + state bucket script + docs | ✅ feito |
| 1 | Import: 3 datasets, 2 SAs, project IAM, dataset WRITER, reports bucket + IAM. `plan` no-op verificado (13 imported, 0 destroyed) | ✅ feito |
| 1c | Import do WIF (pool `github-actions-pool` + provider `github-provider` + binding). `plan` no-op (3 imported, 0 changed) | ✅ feito |
| 2 | Bucket GCS de dados (TF) + refactor boto3→GCS no pipeline; remove AWS (`boto3`, secrets `AWS_*`, `01_aws_s3.sh`). Código pronto; `apply` do bucket após merge | em revisão |
| 3 | (opcional) provider `github` p/ secrets; auth do ingest via WIF (aposenta `GCP_SA_KEY`) | a fazer |
| 4 | Remove bootstrap `00`–`05`; `make bootstrap` → `terraform apply`; tear down AWS | a fazer |
| 5 | (opcional) `terraform plan` em PR (CI), workspaces dev/prod, drift detection | a fazer |

## Layout

```
infra/
├── versions.tf      # terraform >=1.5 (import blocks) + google ~>6.0
├── backend.tf       # gcs backend (bucket {project}-tf-state, prefix susep/)
├── providers.tf     # google provider (ADC auth)
├── variables.tf     # inputs; defaults mirror current infra
├── terraform.tfvars.example
├── bigquery.tf      # datasets + ingestion_log   (Etapa 1)
├── storage.tf       # reports bucket (E1) + data bucket (E2)
├── iam.tf           # service accounts + bindings (Etapa 1)
├── wif.tf           # workload identity federation (Etapa 1)
└── scripts/create-state-bucket.sh
```
