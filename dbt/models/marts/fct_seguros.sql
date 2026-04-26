{# Fact: monthly insurance premium / claim measures by entity x branch.

   Source: `stg_ses_seguros` (~3.5M rows growing each month). Staging
   already does the heavy casts (`damesano` -> `periodo_ref`,
   br_to_numeric on every monetary column). This silver model adds the
   normalisation that staging deliberately skipped:

     * trim() + nullif(trim, '') on the join-key codes so the FKs to
       dim_cia, dim_ramo, dim_grupo line up cleanly.

   No FK enforcement here — silver preserves 100% of the bronze rows.
   Orphan-row filtering is a gold-layer concern (dropping rows with
   no matching dim member changes business semantics, which deserves
   its own decision per mart).

   Loss ratio (sinistro_ocorrido / premio_ganho) is *not* computed
   here. It belongs in gold (Fase 4), where the formula gets locked in
   alongside the rest of the mart contract — sinistro_retido /
   premio_retido is another defensible numerator/denominator pair, and
   picking one in silver would over-commit.

   Materialisation:
     * `table` — view-on-the-fly is fine for 22 rows but expensive at
       3.5M+ where every query re-applies the casts.
     * Monthly partition on `periodo_ref` — almost every analytical
       query filters by period; partition pruning lets BQ skip months
       wholesale.
     * Cluster on `entity_code` — the most common slice ("how did
       this insurer perform"). cogrupo / coramo are too low-cardinality
       (~22 / ~hundreds) to benefit from clustering.
#}

{{ config(
    materialized='table',
    partition_by={
        "field": "periodo_ref",
        "data_type": "date",
        "granularity": "month",
    },
    cluster_by=["entity_code"],
) }}

select
    periodo_ref,

    nullif(trim(entity_code), '')  as entity_code,
    nullif(trim(branch_code), '')  as branch_code,
    nullif(trim(group_code), '')   as group_code,

    -- Premium measures
    premio_direto,
    premio_de_seguros,
    premio_retido,
    premio_ganho,
    premio_emitido2,
    premio_emitido_cap,

    -- Claim measures
    sinistro_direto,
    sinistro_retido,
    sinistro_ocorrido,
    sinistros_ocorridos_cap,
    recuperacao_sinistros_ocorridos_cap,

    -- Reinsurance / commission / other
    desp_com,
    despesa_resseguros,
    receita_resseguro,
    rvne,
    conveniodpvat,
    consorciosefundos,

    _ingestion_date,
    _source_file_name

from {{ ref('stg_ses_seguros') }}
