{# Dimension: grupos de ramos (branch groupings).

   Source: `stg_ses_gruposramos` (~22 rows). SUSEP bundles ramos into
   ~22 groups (Patrimonial, Riscos Especiais, Responsabilidades, ...).
   `group_code` is the join-friendly 2-digit code used downstream;
   `group_id` is SUSEP's internal sequential id and is preserved for
   provenance only.

   Same normalisation as `dim_ramo`: trim() + nullif() on the PK.
#}

select
    nullif(trim(group_code), '')  as group_code,
    trim(group_id)                 as group_id,
    trim(group_name)               as group_name,

    _ingestion_date,
    _source_file_name,
    _extras

from {{ ref('stg_ses_gruposramos') }}
