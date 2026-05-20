{# Curated fact table the insights agent reads.

   Two domain rules that previously lived in the agent's prompt are baked in
   here as tested SQL, so the agent never has to remember them:

     1. Snapshot dedupe — bronze appends a full snapshot per pipeline run. We
        keep only the latest `_ingestion_date`, so every row is current and
        non-duplicated.
     2. Grain — one row per (periodo_ref, entity, group, branch). Measures are
        summed defensively (the source is usually already at this grain) and
        `loss_ratio` is pre-computed.

   Materialised as a partitioned table (by competence month) so agent queries
   scan kilobytes, not the ~600 MB bronze snapshot.
#}

{{ config(
    materialized='table',
    partition_by={'field': 'periodo_ref', 'data_type': 'date', 'granularity': 'month'},
    cluster_by=['group_code', 'branch_code']
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
)

select
    periodo_ref,
    entity_code,
    group_code,
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
group by periodo_ref, entity_code, group_code, branch_code
