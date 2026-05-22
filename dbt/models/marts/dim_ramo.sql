{# Ramo (line of business) code → name. Static lookup, 1 row per branch_code. #}
{{ config(materialized='table') }}

select distinct
    trim(coramo) as branch_code,
    trim(noramo) as branch_name
from {{ source('susep_ses_bronze', 'ses_ramos') }}
where coramo is not null and trim(coramo) != ''
