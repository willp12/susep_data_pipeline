{# Staging view over the bronze `ses_gruposramos` reference table.

   Three-column dimension for grupos de ramos. The source ships UPPERCASE
   column names (`GRAID`, `GRANOME`, `GRACODIGO`) — BigQuery is
   case-insensitive on identifiers, so we just alias to snake_case here.
   `group_code` matches the alias used by `stg_ses_seguros` and
   `stg_ses_cias` so the dimension joins downstream.

   Same scope guardrail as `stg_ses_ramos`: rename only, no trim/nullif —
   that lives in silver/gold (Fase 3).
#}

select
    GRAID      as group_id,
    GRACODIGO  as group_code,
    GRANOME    as group_name,

    _ingestion_date,
    _source_file_name,
    _extras

from `{{ env_var('GCP_PROJECT_ID') }}.{{ env_var('GCP_BQ_DATASET_BRONZE', 'susep_ses_bronze') }}.ses_gruposramos`
