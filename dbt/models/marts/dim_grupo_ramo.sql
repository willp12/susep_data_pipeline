{# Branch-group (grupo de ramos) code → name. The code is the leading 2 digits
   of a ramo (branch_code). Static lookup, ~22 rows. #}
{{ config(materialized='table') }}

select distinct
    trim(GRACODIGO) as ramo_group_code,
    trim(GRANOME)   as ramo_group_name
from {{ source('susep_ses_bronze', 'ses_gruposramos') }}
where GRACODIGO is not null and trim(GRACODIGO) != ''
