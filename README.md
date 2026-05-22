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

1. Instalar `aws` e `gcloud` CLIs (o `gcloud` também traz o `bq`).
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
| `02_gcp_apis.sh`          | Habilita `bigquery.googleapis.com`, `storage.googleapis.com` e `iamcredentials.googleapis.com` (necessária pra impersonação via WIF na CI). |
| `03_gcp_bigquery.sh`      | Cria datasets `susep_ses_bronze`, `susep_ses_staging` e `susep_ses_marts` (location US) + tabela `ingestion_log` particionada por `ingestion_date`, clusterizada por `file_name`. **Nunca faz DELETE/DROP.** |
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

## Agente de insights

Um agente (Claude Agent SDK) que lê as tabelas do BigQuery e escreve um relatório
de insights de negócio em `reports/YYYY-MM-DD.md`. Roda diariamente via GitHub
Actions e abre um PR contra a `main` pra revisão humana.

### Como funciona

- **Fonte preferida:** `susep_ses_marts.fct_seguros` — fato curado (dedup do
  snapshot mais recente embutido, métricas pré-computadas como `loss_ratio`,
  particionado por mês). O agente pode descer pro staging/bronze pra drill-down.
- **Tools (read-only):** `describe_table`, `sample_rows`, `run_sql` (com dry-run
  obrigatório + cap de ~1 GiB por query) e `read_report`.
- **Glossário:** as descrições de coluna vêm do `dbt docs` (manifest gerado por
  `dbt parse`), a partir dos `_models.yml`. Refine-os pra melhorar os insights.
- **Janela:** foca nos últimos 3 anos de `periodo_ref`.
- **Guardrails:** gate default-deny (só as tools acima), `max_turns` e
  `max_budget_usd` (config), além do cap de bytes por query.

### Memória entre runs (continuidade)

Cada run recebe um **digest** dos reports anteriores (datas + títulos dos
insights) injetado no prompt, e pode puxar um report inteiro via `read_report`.
A cada execução o agente escolhe um **modo** (declarado no sumário):

- **deep-dive** — aprofunda um fio de um report anterior, ou
- **novo ângulo** — investiga algo ainda não coberto.

Repetir um achado com o mesmo enquadramento é proibido; só vale reabordar uma
métrica se houver informação nova (novo mês, recorte, causa).

> **Importante:** o histórico considerado é o que está **mergeado na `main`**.
> Como os reports entram via PR, um PR ainda aberto não entra na memória do run
> seguinte — se acumular PRs sem mergear, a continuidade "atrasa".

### Rodar localmente

```bash
# Pré-requisitos: ANTHROPIC_API_KEY no .env e a CLI do Claude Code instalada
npm install -g @anthropic-ai/claude-code
uv run dbt parse --project-dir dbt --profiles-dir dbt   # gera o glossário
uv run python -m src.agent.main                          # escreve reports/<hoje>.md
```

### Em produção (GitHub Actions)

- **`insights.yml`** — `schedule` diário + `workflow_dispatch`. Autentica no GCP
  via Workload Identity Federation (SA `bq-agent-readonly`, só leitura), roda o
  agente e abre um PR com o report. Cada disparo gera um report **novo** sem
  apagar o anterior: o 1º do dia é `YYYY-MM-DD.md`, reruns viram
  `YYYY-MM-DD_2.md`, `_3.md`… (uma PR por report). Runs sobrepostos são
  permitidos (sem `cancel-in-progress`).
- **`ci.yml`** — em push/PR: ruff + mypy + pytest + scan de segredos (gitleaks).
- **Secrets/vars necessários:** secret `ANTHROPIC_API_KEY`, `GCP_WIF_PROVIDER`,
  `GCP_AGENT_SA`; variável `GCP_PROJECT_ID`.

### Git workflow

- `main` é protegida: toda mudança entra via PR.
- Trabalho acontece em feature branches (`feat/`, `fix/`, `chore/`) que mergeiam
  em `develop`. Depois `develop` → `main` via PR.
- [Conventional Commits](https://www.conventionalcommits.org/) obrigatório.

## Estrutura

```
susep-ses-pipeline/
├── .github/workflows/            # insights.yml (agente) + ci.yml (lint/test/secret-scan)
├── scripts/bootstrap/            # provisionamento (vira Terraform na Fase 6)
├── src/
│   ├── main.py                   # entrypoint da pipeline
│   ├── config.py                 # carrega env vars
│   ├── ingestion/                # scraper, hasher, downloader
│   ├── bronze/                   # unzip → parquet
│   ├── loaders/                  # S3 → BigQuery
│   ├── state/                    # ingestion_log
│   └── agent/                    # agente de insights (tools, glossário, histórico, prompt)
├── dbt/
│   └── models/
│       ├── staging/              # stg_ses_seguros (view)
│       └── marts/                # fct_seguros (fato curado lido pelo agente)
├── reports/                      # relatórios gerados pelo agente (YYYY-MM-DD.md)
├── tests/
└── pyproject.toml
```

## Fora de escopo neste MVP

- Terraform (Fase 6)
- Demais CSVs do zip (Fase 2)
- Camadas silver/gold no dbt (Fase 3)
- Separação dev vs prod (Fase 3)
- Slack alerts (Fase 5)
