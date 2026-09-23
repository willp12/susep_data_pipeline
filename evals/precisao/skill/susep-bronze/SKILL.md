---
name: susep-bronze
description: Regras obrigatórias para consultar os dados brutos da SUSEP SES no dataset susep_ses_bronze (ses_seguros e as tabelas de nomes). Use antes de escrever qualquer SQL sobre esse dataset. Explica os snapshots, o formato dos números, as datas, os códigos e onde ficam os nomes oficiais.
---

# Dados brutos da SUSEP SES (`susep_ses_bronze`)

Estas são as mesmas regras que o projeto aplica no dbt. Siga todas, em toda query.

## 1. Um snapshot por carga: filtre sempre o mais recente

`ses_seguros` acumula uma cópia completa da base a cada carga do pipeline,
particionada por `_ingestion_date`. Somar sem filtrar conta cada linha várias
vezes. Filtre sempre pelo snapshot mais recente:

```sql
WHERE _ingestion_date = (SELECT MAX(_ingestion_date) FROM `susep_ses_bronze.ses_seguros`)
```

## 2. Os números estão em texto, com vírgula decimal

Todas as colunas de valor (`premio_direto`, `premio_ganho`, `sinistro_ocorrido`
etc.) são STRING no formato brasileiro, sem separador de milhar: `108252392,92`.
Converta sempre assim:

```sql
SAFE_CAST(REPLACE(premio_direto, ',', '.') AS NUMERIC)
```

`CAST` direto falha. `SAFE_CAST` sem o `REPLACE` devolve NULL para todo valor
com casas decimais, e a soma sai menor sem nenhum aviso.

## 3. Datas

`damesano` é o mês de competência em texto `YYYYMM` (ex.: `202404`). Para virar
data:

```sql
PARSE_DATE('%Y%m%d', damesano || '01')
```

Para filtrar um ano inteiro, `damesano BETWEEN '202401' AND '202412'` também
funciona.

## 4. Códigos

| Coluna | O que é |
| --- | --- |
| `coenti` | seguradora (entidade supervisionada), texto com zeros à esquerda |
| `cogrupo` | grupo econômico (conglomerado) da seguradora. **Não** é grupo de ramos |
| `coramo` | ramo, 4 dígitos. Os 2 primeiros dígitos são o grupo de ramos |

Grupo de ramos = `SUBSTR(coramo, 1, 2)`. Nunca use `cogrupo` para linha de
negócio.

## 5. Nomes oficiais: nunca deduza pelo código

| Nome de | Tabela | Código e nome |
| --- | --- | --- |
| ramo | `ses_ramos` | `coramo`, `noramo` |
| grupo de ramos | `ses_gruposramos` | `GRACODIGO` (2 dígitos), `GRANOME` |
| seguradora | `ses_cias` | `Coenti`, `Noenti` |
| grupo econômico | `ses_grupos_economicos` | `cogrupo`, `nogrupo`, um registro por mês (`damesano`): use o nome do mês mais recente |

Use `TRIM()` dos dois lados do join. No grupo econômico, `01225` é INDEPENDENTE e
`99999` é OUTROS GRUPOS. Os rótulos da SUSEP não são o que se imagina: o grupo de
ramos `01` é Patrimonial, não seguro de vida.

## 6. Medidas derivadas

- Prêmio emitido: `premio_de_seguros + premio_emitido_cap`, com `COALESCE(..., 0)`
  nos dois. Não use `premio_emitido2`.
- Sinistralidade: `SUM(sinistro_ocorrido) / SUM(premio_ganho)`.

## Exemplo

Sinistro ocorrido por mês em 2023, só no snapshot mais recente:

```sql
SELECT
  damesano,
  SUM(SAFE_CAST(REPLACE(sinistro_ocorrido, ',', '.') AS NUMERIC)) AS sinistro_ocorrido
FROM `susep_ses_bronze.ses_seguros`
WHERE _ingestion_date = (SELECT MAX(_ingestion_date) FROM `susep_ses_bronze.ses_seguros`)
  AND damesano BETWEEN '202301' AND '202312'
GROUP BY damesano
ORDER BY damesano
```
