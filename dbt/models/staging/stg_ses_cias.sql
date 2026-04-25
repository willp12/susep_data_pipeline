{# Staging view over the bronze `ses_cias` reference table.

   Four-column dimension: seguradora (entity) and the grupo it belongs to.
   The source ships Capitalised column names (`Coenti`, `Noenti`,
   `Cogrupo`, `Nogrupo`) — BigQuery is case-insensitive on identifiers, so
   we just alias to snake_case. `entity_code` and `group_code` line up
   with the aliases used by `stg_ses_seguros` and `stg_ses_gruposramos`.

   Same scope guardrail as the other two reference views: rename only.
   `Nogrupo` is sometimes NULL and `Cogrupo` is sometimes a blank string
   — both pass through unchanged. Silver/gold can `nullif(trim(...), '')`
   when a clean dimension key is needed.
#}

select
    Coenti   as entity_code,
    Noenti   as entity_name,
    Cogrupo  as group_code,
    Nogrupo  as group_name,

    _ingestion_date,
    _source_file_name,
    _extras

from `{{ env_var('GCP_PROJECT_ID') }}.{{ env_var('GCP_BQ_DATASET_BRONZE', 'susep_ses_bronze') }}.ses_cias`
