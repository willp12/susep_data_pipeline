{# Economic-group (conglomerate) code → name.

   Source is time-varying (one row per coenti per month), so we take the most
   recent name observed for each cogrupo. Notable buckets confirmed in the data:
   01225 = "INDEPENDENTE", 99999 = "OUTROS GRUPOS". #}
{{ config(materialized='table') }}

with ranked as (
    select
        trim(cogrupo) as economic_group_code,
        trim(nogrupo) as economic_group_name,
        row_number() over (
            partition by trim(cogrupo)
            order by damesano desc
        ) as rn
    from {{ source('susep_ses_bronze', 'ses_grupos_economicos') }}
    where cogrupo is not null and trim(cogrupo) != ''
)

select economic_group_code, economic_group_name
from ranked
where rn = 1
