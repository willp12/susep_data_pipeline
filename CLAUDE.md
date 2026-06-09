# Projeto: susep-ses-pipeline (MVP — Fase 1)

Você vai construir um pipeline de engenharia de dados que ingere dados públicos
do SUSEP SES pra BigQuery, usando AWS S3 como storage intermediário. Este é o
**MVP**: rodada manual, local, um único arquivo processado end-to-end.

## Contexto

- **Fonte:** https://www2.susep.gov.br/menuestatistica/SES/principal.aspx
- **Formato:** página HTML com link pra arquivo `.zip` (~500MB) contendo múltiplos CSVs
- **Arquivo alvo do MVP:** `ses_seguros.csv` (os outros CSVs ficam pra Fase 2)
- **Encoding provável:** latin-1 (comum em dados SUSEP — validar ao ler)
- **Storage raw/bronze:** AWS S3
- **Analytics warehouse:** Google BigQuery (projeto pessoal já existente)
- **Transformações:** dbt direto em tabelas BQ (sem escrever parquet de volta)
- **Owner:** uso pessoal, solo dev

## Stack (não substituir sem me perguntar)

- **Python 3.12 EXATO** (`requires-python = ">=3.12,<3.13"` no pyproject)
- **uv** (package manager)
- **dbt-core >=1.11,<1.12** e **dbt-bigquery >=1.11,<1.12**
- **httpx** + **selectolax** (scraping)
- **polars** (processamento CSV)
- **boto3** (AWS), **google-cloud-bigquery**, **google-cloud-storage**
- **pydantic v2** (validação leve de config)
- **structlog** (logs estruturados)
- **pytest**, **ruff**, **pre-commit**

Se o uv resolver reclamar de conflito entre polars e dbt-bigquery (tipicamente
pyarrow ou protobuf), me avisa antes de tentar resolver — provavelmente vamos
separar em dependency groups do uv.

## Decisões já tomadas (não reabrir)

1. dbt escreve silver/gold direto em tabelas BQ (sem parquet em S3)
2. `ingestion_log` é tabela no BQ com schema:
   - `ingestion_date` DATE (partição)
   - `file_name` STRING
   - `file_hash` STRING (SHA256)
   - `source_url` STRING
   - `status` STRING ('ingested' | 'no_change' | 'failed')
   - `run_timestamp` TIMESTAMP
3. Parquet no bronze tem duas colunas extras: `_ingestion_date` e `_source_file_name`
4. Tabela BQ bronze particionada por `_ingestion_date`
5. Nomes fixos:
   - S3 bucket: `susep-ses-data`
   - BQ dataset bronze: `susep_ses_bronze`
   - BQ dataset staging (dbt): `susep_ses_staging`
   - Raw path: `s3://susep-ses-data/raw/{YYYY-MM-DD}/{file_name}_{timestamp}.zip`
   - Bronze path: `s3://susep-ses-data/bronze/ses_seguros/ingestion_date={YYYY-MM-DD}/`
6. Credenciais locais: AWS CLI profile default, `gcloud auth application-default`
7. Sem separação dev/prod neste MVP
8. GCP: usa projeto pessoal existente (ID preenchido no `.env`)

## Estrutura de pastas

```
susep-ses-pipeline/
├── .github/workflows/            # vazio por enquanto (Fase 4)
├── scripts/bootstrap/            # provisionamento de infra (vira Terraform na Fase 6)
│   ├── 00_preflight.sh
│   ├── 01_aws_s3.sh
│   ├── 02_gcp_apis.sh
│   ├── 03_gcp_bigquery.sh
│   └── run_all.sh
├── src/
│   ├── __init__.py
│   ├── main.py                   # entrypoint
│   ├── config.py                 # carrega env vars
│   ├── ingestion/
│   │   ├── scraper.py
│   │   ├── hasher.py
│   │   └── downloader.py
│   ├── bronze/
│   │   └── unzip_to_parquet.py
│   ├── loaders/
│   │   └── bq_loader.py
│   └── state/
│       └── ingestion_log.py
├── dbt/
│   ├── models/staging/stg_ses_seguros.sql
│   ├── dbt_project.yml
│   └── profiles.yml
├── tests/
├── .env.example
├── .gitignore
├── pyproject.toml
├── Makefile
└── README.md
```

## Env vars (.env.example)

```
ENV=dev
AWS_S3_BUCKET=susep-ses-data
AWS_REGION=us-east-1
GCP_PROJECT_ID=<preencher com projeto pessoal existente>
GCP_BQ_DATASET_BRONZE=susep_ses_bronze
GCP_BQ_DATASET_STAGING=susep_ses_staging
SUSEP_SES_URL=https://www2.susep.gov.br/menuestatistica/SES/principal.aspx
```

## Git hygiene (setup inicial)

1. `git init`
2. Primeiro commit na `main` com estrutura vazia
3. Criar branch `develop` a partir da `main`
4. **Branch protection na `main`** (via `gh` CLI se autenticado, senão me dar
   passos pra fazer no browser):
   - Require pull request before merging: **ON**
   - Require linear history: **ON**
   - Require conversation resolution before merging: **ON**
   - Required approvals: **OFF** (sou solo dev, GitHub não permite self-approve)
   - Include administrators: **OFF** (senão eu mesmo travo o repo)
5. Todo trabalho em feature branches (`feat/`, `fix/`, `chore/`) mergeando em
   `develop` via PR, e depois `develop` → `main` via PR
6. Conventional commits

## Checkpoints (pare em cada um)

### Checkpoint 1 — Setup do repo
- Estrutura de pastas, pyproject com uv, ruff, pre-commit, .env.example
- README com passo-a-passo de setup local
- Makefile com targets: `install`, `lint`, `test`, `run`, `dbt-build`, `bootstrap`
- Git init, branches, branch protection
- **Validação do ambiente:** após `uv sync`, rodar:
```
  uv run python -c "import dbt.version; print(dbt.version.__version__)"
  uv run python -c "import polars; print(polars.__version__)"
```
  Ambos devem rodar sem erro. Se houver conflito de pyarrow/protobuf entre
  polars e dbt-bigquery, reportar antes de prosseguir.
- **PARA AQUI** e me mostra o que fez.

### Checkpoint 2 — Bootstrap de infra
Cria `scripts/bootstrap/` com scripts bash **idempotentes** (rodáveis múltiplas
vezes sem erro). Escreve com a migração pra Terraform em mente.

**`00_preflight.sh`** — valida ambiente:
- `aws sts get-caller-identity` retorna sucesso
- `gcloud auth application-default print-access-token` retorna sucesso
- `GCP_PROJECT_ID` setado no .env
- Mostra account AWS + projeto GCP que vai ser usado e pede confirmação (y/N)

**`01_aws_s3.sh`** — cria bucket `susep-ses-data`:
- Região `us-east-1` (configurável via env)
- Block public access: **todas as 4 flags ON**
- Versioning: **enabled**
- Default encryption: **SSE-S3** (AES256, grátis)
- Lifecycle rule em `raw/`: transition pra Glacier Instant Retrieval após 30
  dias; expira noncurrent versions após 90 dias
- Lifecycle rule em `bronze/`: fica em Standard
- Tags: `Project=susep-ses-pipeline`, `Env=dev`, `ManagedBy=bootstrap-script`
- Se bucket já existe e pertence a mim, aplica só as configs (idempotente via
  `put-bucket-*`). Se pertence a outro account, falha com mensagem clara.

**`02_gcp_apis.sh`** — habilita APIs no projeto existente:
- `bigquery.googleapis.com`
- `storage.googleapis.com` (caso GCS seja staging pro load no BQ)

**`03_gcp_bigquery.sh`** — cria datasets e tabela de log:
- Dataset `susep_ses_bronze` (location `US` multi-region)
- Dataset `susep_ses_staging`
- Tabela `susep_ses_bronze.ingestion_log` com schema acima, particionada por
  `ingestion_date`, clusterizada por `file_name`
- Verifica existência antes de criar. **Nunca DELETE** nestes scripts.

**`run_all.sh`** — roda 00 → 01 → 02 → 03 em sequência. Para no primeiro erro.

No README, seção "Primeira execução":
1. Instalar `aws` e `gcloud` CLIs
2. `aws configure` e `gcloud auth application-default login`
3. `gcloud config set project <id-do-projeto-pessoal>`
4. Copiar `.env.example` pra `.env` e preencher `GCP_PROJECT_ID`
5. `bash scripts/bootstrap/run_all.sh`

**PARA AQUI.** Rodo o bootstrap e confirmo antes de seguir.

### Checkpoint 3 — Scraper
- `scraper.py` baixa HTML da URL do SUSEP e extrai link do zip mais recente
- User-Agent realista, timeout, retry
- Teste manual: `python -m src.ingestion.scraper` imprime a URL do zip
- **PARA AQUI.** Confirmo URL antes de baixar 500MB.

### Checkpoint 4 — Ingestion log
- `ingestion_log.py` com `get_latest_hash()` e `insert_entry()`
- **PARA AQUI.**

### Checkpoint 5 — Download + hash + upload S3 raw
- `hasher.py` (SHA256) e `downloader.py`
- Lógica: baixa zip (streaming pra disco temp), calcula SHA256, compara com
  último hash do log. Se igual → loga `no_change` e retorna. Se diferente →
  upload pro S3 em `raw/` e insere log `ingested`
- **PARA AQUI.** Primeira vez baixando 500MB de verdade.

### Checkpoint 6 — Bronze
- `unzip_to_parquet.py`: extrai `ses_seguros.csv` do zip, lê com polars
  (tenta utf-8 e fallback pra latin-1), adiciona `_ingestion_date` e
  `_source_file_name`, escreve parquet no S3 com particionamento
- **PARA AQUI.** Checo o parquet antes de carregar.

### Checkpoint 7 — Load BQ + dbt staging
- `bq_loader.py` carrega parquet do S3 pra `susep_ses_bronze.ses_seguros`,
  particionada por `_ingestion_date`
  (BQ não lê S3 nativamente — baixa o parquet pra local temp e sobe via load
  job, OU via GCS intermediário. Escolhe o mais simples e explica a escolha
  no PR.)
- Projeto dbt com profile apontando pra `susep_ses_staging`, modelo único
  `stg_ses_seguros` com renames/casts básicos, materializado como view
- `main.py` orquestra: scrape → hash-check → download → upload raw → bronze
  parquet → load BQ → `dbt build`
- **PARA AQUI.** Rodada end-to-end manual.

## Fora de escopo (NÃO fazer agora)

- GitHub Actions / cron (Fase 4)
- Terraform (Fase 6)
- Múltiplos CSVs do zip (Fase 2)
- Silver/gold no dbt (Fase 3)
- dev vs prod separados (Fase 3)
- pydantic schema contracts robustos (Fase 2)
- Slack alerts (Fase 5)
- Testes automatizados além de smoke test manual

## Regras pra você, Claude Code

- Commits pequenos e conventional
- Ruff + mypy passando antes de cada commit
- Se uma dependência que sugeri não servir, me avisa antes de trocar
- Se o SUSEP devolver erro, mostra o HTML cru — não chuta parsing
- Não roda a pipeline end-to-end até o Checkpoint 7
- Nunca commita `.env`, credenciais, ou o zip de 500MB
- Para em **todo** checkpoint e espera minha confirmação
