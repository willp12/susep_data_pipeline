{# Insurer (entity) code → name. Static lookup, ~758 rows. #}
{{ config(materialized='table') }}

select distinct
    trim(Coenti) as entity_code,
    trim(Noenti) as entity_name
from {{ source('susep_ses_bronze', 'ses_cias') }}
where Coenti is not null and trim(Coenti) != ''
