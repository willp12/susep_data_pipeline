# susep-ses-pipeline

Pipeline de engenharia de dados que ingere estatísticas públicas do
[SUSEP SES](https://www2.susep.gov.br/menuestatistica/SES/principal.aspx) para
BigQuery, usando AWS S3 como storage intermediário e dbt para transformações.

> **Status:** MVP — Fase 1 (rodada manual, local, um único arquivo end-to-end).

## Stack

- Python 3.12 (exato)
- [uv](https://docs.astral.sh/uv/) como package manager
- httpx + selectolax (scraping)
- polars (processamento CSV)
- boto3 + google-cloud-bigquery + google-cloud-storage
- dbt-core / dbt-bigquery (>=1.11,<1.12)
- pydantic v2, structlog
- ruff, mypy, pre-commit, pytest

## Setup local

### Pré-requisitos

1. **Python 3.12** — o `uv` cuida de instalar caso não esteja presente.
2. **uv** — instalar conforme [docs oficiais](https://docs.astral.sh/uv/).
3. **AWS CLI** — `aws --version` deve responder.
4. **Google Cloud SDK** — `gcloud --version` deve responder.

### Instalação

```bash
# Clone e entra no diretório
git clone <repo-url> susep-ses-pipeline
cd susep-ses-pipeline

# Sincroniza dependências (cria .venv automaticamente) e instala pre-commit
make install

# Ou manualmente:
uv sync --all-groups
uv run pre-commit install
```

### Validação do ambiente

Após `uv sync`, rode:

```bash
uv run python -c "import dbt.version; print(dbt.version.__version__)"
uv run python -c "import polars; print(polars.__version__)"
```

Ambos devem rodar sem erro. Se houver conflito de `pyarrow`/`protobuf` entre
polars e dbt-bigquery, reportar antes de prosseguir.

## Primeira execução (bootstrap de infra)

1. Instalar `aws` e `gcloud` CLIs (o `gcloud` também traz o `bq`). Ter `jq`
   instalado (usado pelo preflight).
2. `aws configure` (usa profile default) e `gcloud auth application-default login`.
3. `gcloud config set project <id-do-projeto-pessoal>`.
4. Copiar `.env.example` para `.env` e preencher `GCP_PROJECT_ID`.
5. `make bootstrap` (ou `bash scripts/bootstrap/run_all.sh`).

Os scripts são **idempotentes** — podem ser re-rodados sem erro; convergem a
configuração viva pro estado desejado em vez de recriar recursos:

| Script                    | O que faz                                                              |
| ------------------------- | ---------------------------------------------------------------------- |
| `00_preflight.sh`         | Valida AWS/GCP creds, `.env`, CLIs, e pede confirmação interativa.     |
| `01_aws_s3.sh`            | Cria bucket `susep-ses-data` (ou converge config se já existir): block public access, versioning, SSE-S3, lifecycle (raw → Glacier IR após 30d; expira noncurrent versions), tags. |
| `02_gcp_apis.sh`          | Habilita `bigquery.googleapis.com` e `storage.googleapis.com`.         |
| `03_gcp_bigquery.sh`      | Cria datasets `susep_ses_bronze` e `susep_ses_staging` (location US) + tabela `ingestion_log` particionada por `ingestion_date`, clusterizada por `file_name`. **Nunca faz DELETE/DROP.** |
| `run_all.sh`              | Roda `00 → 01 → 02 → 03`, para no primeiro erro.                        |

Para rodar não-interativamente (pular o prompt de confirmação do preflight),
setar `BOOTSTRAP_ASSUME_YES=1`.

## Desenvolvimento

| Comando           | Descrição                                                  |
| ----------------- | ---------------------------------------------------------- |
| `make install`    | Sincroniza dependências e instala hooks de pre-commit      |
| `make lint`       | ruff check + ruff format --check + mypy                    |
| `make fmt`        | Autoformata (ruff format + ruff --fix)                     |
| `make test`       | Roda pytest                                                |
| `make run`        | Executa a pipeline (`python -m src.main`)                  |
| `make dbt-build`  | Roda `dbt build` no projeto `dbt/`                         |
| `make bootstrap`  | Executa scripts de provisionamento de infra                |

### Git workflow

- `main` é protegida: toda mudança entra via PR.
- Trabalho acontece em feature branches (`feat/`, `fix/`, `chore/`) que mergeiam
  em `develop`. Depois `develop` → `main` via PR.
- [Conventional Commits](https://www.conventionalcommits.org/) obrigatório.

## Estrutura

```
susep-ses-pipeline/
├── .github/workflows/            # CI (Fase 4)
├── scripts/bootstrap/            # provisionamento (vira Terraform na Fase 6)
├── src/
│   ├── main.py                   # entrypoint
│   ├── config.py                 # carrega env vars
│   ├── ingestion/                # scraper, hasher, downloader
│   ├── bronze/                   # unzip → parquet
│   ├── loaders/                  # S3 → BigQuery
│   └── state/                    # ingestion_log
├── dbt/
│   └── models/staging/
├── tests/
└── pyproject.toml
```

## Fora de escopo neste MVP

- GitHub Actions / cron agendado (Fase 4)
- Terraform (Fase 6)
- Demais CSVs do zip (Fase 2)
- Camadas silver/gold no dbt (Fase 3)
- Separação dev vs prod (Fase 3)
- Slack alerts (Fase 5)
