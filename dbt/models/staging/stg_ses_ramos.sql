{# Staging view over the bronze `ses_ramos` reference table.

   Two-column dimension: ramo code -> ramo name. Bronze stores both as
   STRING (no inference); we only rename to the canonical snake_case used
   across staging. `branch_code` matches the alias used by
   `stg_ses_seguros` so silver/gold joins line up.

   Deliberately *not* doing here:
     * trim() / nullif() — the source has trailing whitespace on codes
       and blank-string placeholders for missing values. Same call as
       `stg_ses_seguros`: keep staging thin, normalise in silver/gold.
#}

select
    coramo  as branch_code,
    noramo  as branch_name,

    _ingestion_date,
    _source_file_name,
    _extras

from `{{ env_var('GCP_PROJECT_ID') }}.{{ env_var('GCP_BQ_DATASET_BRONZE', 'susep_ses_bronze') }}.ses_ramos`
