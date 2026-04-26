{# Fact: monthly insurance premium / claim measures by entity x branch.

   Source: `stg_ses_seguros` (~3.5M rows growing each month). Staging
   already does the heavy casts (`damesano` -> `periodo_ref`,
   br_to_numeric on every monetary column). This silver model adds the
   normalisation that staging deliberately skipped:

     * trim() + nullif(trim, '') on the join-key codes so the FKs to
       dim_cia (entity_code) and dim_ramo (branch_code) line up cleanly.

   No FK enforcement here — silver preserves 100% of the bronze rows.
   Orphan-row filtering is a gold-layer concern (dropping rows with
   no matching dim member changes business semantics, which deserves
   its own decision per mart).

   Loss ratio (sinistro_ocorrido / premio_ganho) is *not* computed
   here. It belongs in gold, where the formula gets locked in
   alongside the rest of the mart contract — sinistro_retido /
   premio_retido is another defensible numerator/denominator pair, and
   picking one in silver would over-commit.

   ----------------------------------------------------------------
   Naming caveat: `group_code` here is NOT a foreign key

   This column comes from `ses_seguros.cogrupo` and was named
   `group_code` before we knew what it actually meant. Fase 4
   investigation showed:

     * 5 digits always, 116 distinct values (e.g. '01225', '99999',
       '00027') — values like 99999 (789k rows) likely mean
       "agregado/total/não aplicável".
     * Does NOT match `dim_grupo.group_code` (2-digit, 22 values).
       That dimension models "grupo de ramos" — bundles of insurance
       branches; the empirical link to fct_seguros is via
       `branch_code` (4d) -> `substr(_, 1, 2)` -> `dim_grupo`. See
       the enrichment in `dim_ramo` (group_code, group_name,
       branch_full_name).
     * Does NOT match `dim_cia.corporate_group_code` either (0/116).

   So `group_code` here is "código SUSEP interno do tipo de
   contrato/modalidade" — kept for traceability only. Don't join it
   to any dim. If you want the friendly grupo-de-ramos name, go via
   `dim_ramo.branch_full_name` after joining on `branch_code`.

   Renaming was considered (Fase 4 decision A) but rejected — the
   column existed in Ck 3.2 with this name, and changing it now
   would force a coordinated rebuild of every consumer. Kept as-is
   with this docstring as the authoritative warning.
   ----------------------------------------------------------------

   Materialisation:
     * `table` — view-on-the-fly is fine for 22 rows but expensive at
       3.5M+ where every query re-applies the casts.
     * Monthly partition on `periodo_ref` — almost every analytical
       query filters by period; partition pruning lets BQ skip months
       wholesale.
     * Cluster on `entity_code` — the most common slice ("how did
       this insurer perform"). branch_code / group_code are too low-
       cardinality (hundreds / 116) to benefit from clustering.
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
    -- group_code: NOT a FK. See header docstring for full warning.
    -- For the friendly "grupo de ramos" name, join via
    -- dim_ramo.branch_full_name on branch_code.
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
