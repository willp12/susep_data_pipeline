{# Gold mart: solvency snapshot per seguradora per month, 2020+.

   First gold mart in the project. Joins the silver fact (`fct_seguros`),
   the bronze-staging solvency snapshot (`stg_ses_pl_margem`), and the
   `dim_cia` for the friendly seguradora name. One row per
   (periodo_ref, entity_code).

   Columns:

     periodo_ref               first day of the month (DATE).
     entity_code               raw SUSEP code, kept for joins.
     noenti                    user-friendly seguradora name.
     valor_pl                  patrimônio líquido at month-end.
     cmr                       capital mínimo requerido at month-end.
     premios_emitidos          premio_de_seguros + premio_emitido_cap
                               for the month, NULLs treated as zero.
     premios_emitidos_t12m     same metric summed over the trailing 12
                               calendar months (current + 11 previous),
                               via date-range join so the count is
                               anchored to the calendar, not to row
                               adjacency. Entities with less than 12
                               months of history get a partial sum.
     cmr_over_premios_t12m     cmr / premios_emitidos_t12m. The asked-
                               for ratio: a measure of how many months
                               of premium volume the regulator demands
                               as minimum capital. SAFE_DIVIDE so a
                               zero / NULL denominator yields NULL,
                               not an error.

   Filter: periodo_ref >= 2020-01-01. The trailing 12m sum is computed
   over the full history first, so January 2020 reflects all of 2019.

   Materialised as `table` (gold layer convention), partitioned by
   month on periodo_ref and clustered on entity_code, mirroring
   `fct_seguros` so most queries prune cleanly.

   Caveat baked into a comment by the join: PL/CMR data starts in
   1999-05; ses_seguros data starts in 1995-01. For entities with
   reported premios but no PL/CMR row in stg_ses_pl_margem, the LEFT
   JOIN returns NULL — the row is preserved so consumers see the
   whole population.
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

with premios_monthly as (
    -- Aggregate to monthly grain per entity. fct_seguros is by branch
    -- + entity, so we collapse over branches here. Coalesce to 0 so a
    -- row with one column NULL still contributes the other column's
    -- value; the SUM then turns "all NULL" months into 0 (not NULL),
    -- which is the right neutral element for a trailing-12m total.
    select
        f.entity_code,
        f.periodo_ref,
        sum(
            coalesce(f.premio_de_seguros, 0)
            + coalesce(f.premio_emitido_cap, 0)
        ) as premios_emitidos
    from {{ ref('fct_seguros') }} f
    -- No date filter here on purpose — trailing 12m for 2020-Jan
    -- needs the 2019 history.
    group by f.entity_code, f.periodo_ref
),

premios_with_t12 as (
    -- Self-join on a date range. ROWS-based windows would be wrong
    -- when an entity has a gap in periodo_ref: BETWEEN DATE_SUB(...,
    -- INTERVAL 11 MONTH) AND current_period anchors the 12-month
    -- window to the calendar, not to adjacency.
    select
        a.entity_code,
        a.periodo_ref,
        a.premios_emitidos,
        sum(b.premios_emitidos) as premios_emitidos_t12m
    from premios_monthly a
    left join premios_monthly b
        on a.entity_code = b.entity_code
       and b.periodo_ref between date_sub(a.periodo_ref, interval 11 month)
                              and a.periodo_ref
    group by a.entity_code, a.periodo_ref, a.premios_emitidos
),

final as (
    select
        p.periodo_ref,
        p.entity_code,
        c.entity_name                                                    as noenti,

        pl.pl                                                            as valor_pl,
        pl.cmr                                                           as cmr,

        p.premios_emitidos,
        p.premios_emitidos_t12m,

        safe_divide(pl.cmr, p.premios_emitidos_t12m)                     as cmr_over_premios_t12m

    from premios_with_t12 p
    left join {{ ref('stg_ses_pl_margem') }} pl
        on  p.entity_code = pl.entity_code
        and p.periodo_ref = pl.periodo_ref
    left join {{ ref('dim_cia') }} c
        on  p.entity_code = c.entity_code
    where p.periodo_ref >= date '2020-01-01'
)

select * from final
