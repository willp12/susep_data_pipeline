{# CNSeg ramo taxonomy: branch_code → (segmento, grupo_1, grupo_2).

   A curated mapping maintained by CNSeg, distinct from SUSEP's own ramo-group
   classification (dim_grupo_ramo). It rolls the ~180 ramos up into 4 segmentos
   → ~16 grupo_1 → ~40 grupo_2. Source is a checked-in seed (cnseg_ramos), not
   the SUSEP ingestion, since it's a hand-maintained reference table.

   1 row per branch_code (the seed is already deduped to a single mapping per
   code — sub-description variants that share a 4-digit code collapse to the
   same segmento/grupo_1/grupo_2). Static lookup, ~180 rows. #}
{{ config(materialized='table') }}

select
    lpad(trim(ramo_code), 4, '0') as branch_code,
    trim(segmento)                as cnseg_segmento,
    trim(grupo_1)                 as cnseg_grupo_1,
    trim(grupo_2)                 as cnseg_grupo_2
from {{ ref('cnseg_ramos') }}
where ramo_code is not null and trim(ramo_code) != ''
