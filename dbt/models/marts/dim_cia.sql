{# Dimension: seguradoras (insurance companies).

   Source: `stg_ses_cias` (~758 rows). Each row is a regulated entity;
   each entity may belong to a corporate group (parent holding).

   Naming carefully here: SUSEP overloads the word "grupo".
     * In `ses_gruposramos` ("grupo de ramos"), grupo means a bundle
       of insurance branches — that's `dim_grupo`.
     * In `ses_cias` ("grupo de seguradoras"), grupo means corporate
       parent — different concept. Renamed here to
       `corporate_group_code` / `corporate_group_name` to keep the
       semantics explicit and prevent accidental joins to `dim_grupo`.

   Many rows have a blank corporate group (independent insurers).
   `nullif(trim(...), '')` converts those to clean NULLs.
#}

select
    nullif(trim(entity_code), '')  as entity_code,
    trim(entity_name)              as entity_name,

    nullif(trim(group_code), '')   as corporate_group_code,
    trim(group_name)               as corporate_group_name,

    _ingestion_date,
    _source_file_name,
    _extras

from {{ ref('stg_ses_cias') }}
