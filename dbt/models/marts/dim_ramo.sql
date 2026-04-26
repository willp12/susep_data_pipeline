{# Dimension: ramos (insurance branches).

   Source: `stg_ses_ramos` (~161 rows). The staging view passes
   SUSEP's column casing through unchanged with trailing whitespace
   intact (`'0776      '`). Here in silver we apply the universal
   normalisation that the staging layer deliberately skipped:

     * trim() on every string — kills the right-padding so that
       fct_seguros joins line up with dim_ramo.
     * nullif(trim(...), '') on the PK — converts the rare blank
       row (if any) into NULL rather than a meaningless empty key.

   Materialised as `table` via the marts default in `dbt_project.yml`.
   No partition/cluster — too small to matter.
#}

select
    nullif(trim(branch_code), '')  as branch_code,
    trim(branch_name)              as branch_name,

    _ingestion_date,
    _source_file_name,
    _extras

from {{ ref('stg_ses_ramos') }}
