{# Curated fact table the insights agent reads.

   Two domain rules that previously lived in the agent's prompt are baked in
   here as tested SQL, so the agent never has to remember them:

     1. Snapshot dedupe — bronze appends a full snapshot per pipeline run. We
        keep only the latest `_ingestion_date`, so every row is current and
        non-duplicated.
     2. Grain — one row per (periodo_ref, entity, economic group, branch).
        `economic_group_code` is the insurer's conglomerate (cogrupo), NOT the
        line of business. Measures are summed defensively (the source is usually
        already at this grain) and `loss_ratio` is pre-computed.

   Names are joined from the dim_* lookups (1:1, no grain change) so the agent
   reads real labels instead of inferring them: branch_name, ramo_group_name,
   entity_name, economic_group_name (e.g. 01225 → "INDEPENDENTE",
   99999 → "OUTROS GRUPOS").

   Materialised as a partitioned table (by competence month) so agent queries
   scan kilobytes, not the ~600 MB bronze snapshot.
#}

{{ config(
    materialized='table',
    partition_by={'field': 'periodo_ref', 'data_type': 'date', 'granularity': 'month'},
    cluster_by=['economic_group_code', 'branch_code']
) }}

with latest as (
    select max(_ingestion_date) as ingestion_date
    from {{ ref('stg_ses_seguros') }}
),

current_snapshot as (
    select s.*
    from {{ ref('stg_ses_seguros') }} as s
    cross join latest
    where s._ingestion_date = latest.ingestion_date
),

agg as (
    select
        periodo_ref,
        entity_code,
        economic_group_code,
        branch_code,

        sum(premio_direto)                         as premio_direto,
        sum(premio_de_seguros)                     as premio_de_seguros,
        sum(premio_retido)                         as premio_retido,
        sum(premio_ganho)                          as premio_ganho,
        sum(sinistro_direto)                       as sinistro_direto,
        sum(sinistro_retido)                       as sinistro_retido,
        sum(desp_com)                              as desp_com,
        sum(premio_emitido2)                       as premio_emitido2,
        sum(premio_emitido_cap)                    as premio_emitido_cap,
        sum(despesa_resseguros)                    as despesa_resseguros,
        sum(sinistro_ocorrido)                     as sinistro_ocorrido,
        sum(receita_resseguro)                     as receita_resseguro,
        sum(sinistros_ocorridos_cap)               as sinistros_ocorridos_cap,
        sum(recuperacao_sinistros_ocorridos_cap)   as recuperacao_sinistros_ocorridos_cap,
        sum(rvne)                                  as rvne,
        sum(conveniodpvat)                         as conveniodpvat,
        sum(consorciosefundos)                     as consorciosefundos,

        -- Loss ratio = incurred claims / earned premium. SAFE_DIVIDE guards /0.
        safe_divide(sum(sinistro_ocorrido), sum(premio_ganho)) as loss_ratio,

        max(_ingestion_date)                       as _ingestion_date

    from current_snapshot
    group by periodo_ref, entity_code, economic_group_code, branch_code
)

select
    a.*,
    -- Canonical "prêmio emitido" = insurance premium + capitalization premium.
    -- COALESCE so a row carrying only one segment isn't nulled out. The raw
    -- SUSEP field premio_emitido2 stays above for traceability.
    coalesce(a.premio_de_seguros, 0) + coalesce(a.premio_emitido_cap, 0) as premio_emitido,
    substr(a.branch_code, 1, 2)  as ramo_group_code,
    r.branch_name,
    gr.ramo_group_name,
    -- CNSeg taxonomy (parallel to SUSEP's ramo group); NULL when a ramo isn't
    -- in the de-para — covered by a warn-level coverage test.
    c.cnseg_segmento,
    c.cnseg_grupo_1,
    c.cnseg_grupo_2,
    e.entity_name,
    ge.economic_group_name
from agg as a
left join {{ ref('dim_ramo') }}            as r  on r.branch_code = a.branch_code
left join {{ ref('dim_grupo_ramo') }}      as gr on gr.ramo_group_code = substr(a.branch_code, 1, 2)
left join {{ ref('dim_cnseg') }}           as c  on c.branch_code = a.branch_code
left join {{ ref('dim_entidade') }}        as e  on e.entity_code = a.entity_code
left join {{ ref('dim_grupo_economico') }} as ge on ge.economic_group_code = a.economic_group_code
