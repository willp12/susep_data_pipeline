{# Staging view over the bronze `ses_pl_margem` table.

   Monthly solvency snapshot per seguradora (entity): patrimônio
   líquido (PL), PL ajustado, margem de solvência, capital mínimo
   requerido (CMR), and the accounting/economic adjustments that
   bridge raw PL to PL ajustado.

   Same shape of casts as `stg_ses_seguros`:
     * `damesano` (YYYYMM text) -> `periodo_ref` DATE, first of month.
     * Every monetary column -> NUMERIC via the `br_to_numeric` macro.
     * `coenti` stays as STRING (entity code with leading zeros).

   Same scope guardrails as the other staging models — rename + cast
   only, no trim/nullif. Normalisation lives in silver / marts when /
   if a fct_pl_margem is added later.
#}

select
    parse_date('%Y%m%d', damesano || '01')   as periodo_ref,
    coenti                                    as entity_code,

    {{ br_to_numeric('plajustado')        }}  as pl_ajustado,
    {{ br_to_numeric('margem')            }}  as margem,
    {{ br_to_numeric('pl')                }}  as pl,
    {{ br_to_numeric('AjustesContabeis')  }}  as ajustes_contabeis,
    {{ br_to_numeric('AjustesEconomicos') }}  as ajustes_economicos,
    {{ br_to_numeric('NovoPla')           }}  as novo_pla,
    {{ br_to_numeric('CMR')               }}  as cmr,

    _ingestion_date,
    _source_file_name

from `{{ env_var('GCP_PROJECT_ID') }}.{{ env_var('GCP_BQ_DATASET_BRONZE', 'susep_ses_bronze') }}.ses_pl_margem`
