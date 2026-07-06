{# Staging view over the bronze `ses_seguros` table.

   Bronze stores every column as STRING on purpose (polars can't safely infer
   schema with European decimals mid-file). This model does the two cheap
   casts that unblock downstream analytics:

     * `damesano` (YYYYMM text) → `periodo_ref` DATE, first of month.
     * Every monetary column → NUMERIC via the `br_to_numeric` macro.

   Codes (`coenti`, `cogrupo`, `coramo`) stay as STRING — they're IDs with
   leading zeros, not numbers.

   Deliberately *not* doing here:
     * null-standardisation (empty-string vs NULL) — bronze already reads
       empty cells as NULL.
     * cross-table enrichment — that's silver/gold (out of scope).
#}

select
    parse_date('%Y%m%d', damesano || '01')                as periodo_ref,
    coenti                                                 as entity_code,
    cogrupo                                                as economic_group_code,
    coramo                                                 as branch_code,

    {{ br_to_numeric('premio_direto')                    }} as premio_direto,
    {{ br_to_numeric('premio_de_seguros')                }} as premio_de_seguros,
    {{ br_to_numeric('premio_retido')                    }} as premio_retido,
    {{ br_to_numeric('premio_ganho')                     }} as premio_ganho,
    {{ br_to_numeric('sinistro_direto')                  }} as sinistro_direto,
    {{ br_to_numeric('sinistro_retido')                  }} as sinistro_retido,
    {{ br_to_numeric('desp_com')                         }} as desp_com,
    {{ br_to_numeric('premio_emitido2')                  }} as premio_emitido2,
    {{ br_to_numeric('premio_emitido_cap')               }} as premio_emitido_cap,
    {{ br_to_numeric('despesa_resseguros')               }} as despesa_resseguros,
    {{ br_to_numeric('sinistro_ocorrido')                }} as sinistro_ocorrido,
    {{ br_to_numeric('receita_resseguro')                }} as receita_resseguro,
    {{ br_to_numeric('sinistros_ocorridos_cap')          }} as sinistros_ocorridos_cap,
    {{ br_to_numeric('recuperacao_sinistros_ocorridos_cap') }} as recuperacao_sinistros_ocorridos_cap,
    {{ br_to_numeric('rvne')                             }} as rvne,
    {{ br_to_numeric('conveniodpvat')                    }} as conveniodpvat,
    {{ br_to_numeric('consorciosefundos')                }} as consorciosefundos,

    _ingestion_date,
    _source_file_name

from `{{ env_var('GCP_PROJECT_ID') }}.{{ env_var('GCP_BQ_DATASET_BRONZE', 'susep_ses_bronze') }}.ses_seguros`
