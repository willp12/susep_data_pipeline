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

> Estes passos ficam disponíveis após o **Checkpoint 2**. Atualmente o diretório
> `scripts/bootstrap/` está vazio.

1. Instalar `aws` e `gcloud` CLIs.
2. `aws configure` (usa profile default) e `gcloud auth application-default login`.
3. `gcloud config set project <id-do-projeto-pessoal>`.
4. Copiar `.env.example` para `.env` e preencher `GCP_PROJECT_ID`.
5. `bash scripts/bootstrap/run_all.sh` — cria bucket S3, habilita APIs GCP, cria
   datasets BigQuery e a tabela `ingestion_log`.

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
