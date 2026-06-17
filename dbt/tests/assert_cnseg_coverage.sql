{# Warn (don't fail) when a *currently-active* ramo has no CNSeg mapping.

   Scoped to the recent window (last 4 years of periodo_ref) on purpose: the
   de-para only covers modern 4-digit ramos, while the fact also holds legacy
   2-digit codes that stopped reporting decades ago (last premium in 2000) —
   flagging those would be permanent noise. A returned row is an unmapped ramo
   with recent issued premium — an actionable candidate for the cnseg_ramos
   seed. Visibility check, not a hard gate. #}
{{ config(severity='warn') }}

with bounds as (
    select date_sub(max(periodo_ref), interval 4 year) as cutoff
    from {{ ref('fct_seguros') }}
)

select
    f.branch_code,
    any_value(f.branch_name)   as branch_name,
    sum(f.premio_emitido)      as premio_emitido_recente
from {{ ref('fct_seguros') }} as f
cross join bounds as b
left join {{ ref('dim_cnseg') }} as c on c.branch_code = f.branch_code
where c.branch_code is null
  and f.periodo_ref >= b.cutoff
group by f.branch_code
having sum(f.premio_emitido) > 0
