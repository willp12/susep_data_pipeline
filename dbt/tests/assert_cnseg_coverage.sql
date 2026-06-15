{# Warn (don't fail) when ramos carrying premium have no CNSeg mapping.

   Some ramos may legitimately be absent from the CNSeg de-para, so this is a
   visibility check, not a hard gate. Each returned row is an unmapped ramo
   with non-zero issued premium — a candidate to add to the cnseg_ramos seed. #}
{{ config(severity='warn') }}

select
    f.branch_code,
    any_value(f.branch_name)   as branch_name,
    sum(f.premio_emitido)      as premio_emitido_total
from {{ ref('fct_seguros') }} as f
left join {{ ref('dim_cnseg') }} as c on c.branch_code = f.branch_code
where c.branch_code is null
group by f.branch_code
having sum(f.premio_emitido) > 0
