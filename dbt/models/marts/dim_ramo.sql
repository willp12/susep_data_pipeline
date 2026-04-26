{# Dimension: ramos (insurance branches), enriched with group context.

   Source: `stg_ses_ramos` (~161 rows). The staging view passes
   SUSEP's column casing through unchanged with trailing whitespace
   intact (`'0776      '`). Here in silver we apply the universal
   normalisation that the staging layer deliberately skipped:

     * trim() on every string — kills the right-padding so that
       fct_seguros joins line up with dim_ramo.
     * nullif(trim(...), '') on the PK — converts the rare blank row
       (if any) into NULL rather than a meaningless empty key.

   ---------------------------------------------------------------
   Enrichment (Fase 4)

   `branch_full_name` is the user-facing label that joins the group
   name with the branch name, e.g.

       branch_code='0819'
       branch_name='0819 - Crédito à Exp. Risco Comer(RUN OFF)'
       group_code='08'   (derived from branch_code prefix)
       group_name='08 - Crédito'
       branch_full_name='08 - Crédito / 0819 - Crédito à Exp. Risco Comer(RUN OFF)'

   The relationship was discovered empirically: every 4-digit ramo
   code in `ses_ramos.csv` starts with the 2-digit grupo code in
   `ses_gruposramos.csv`. Verified 161/161 ramos map cleanly to a
   group via `substr(branch_code, 1, 2)`.

   Caveat for downstream joins to fct_seguros: the source has
   ~555k rows of legacy 2-digit branch_codes from 1995-2000, when
   SUSEP used a 2-digit codification. dim_ramo holds **only the
   4-digit ramos** (the catalog SUSEP currently publishes), so a
   LEFT JOIN from fct will return NULL `branch_full_name` for those
   pre-2001 rows. That's a deliberate choice (decision B of Fase 4):
   no manual 2d->4d remapping table — accepting NULL is honest, and
   forcing one would require sourcing data SUSEP doesn't publish.
#}

with ramo as (
    select
        nullif(trim(branch_code), '')  as branch_code,
        trim(branch_name)              as branch_name,

        _ingestion_date,
        _source_file_name,
        _extras
    from {{ ref('stg_ses_ramos') }}
)

select
    r.branch_code,
    r.branch_name,

    substr(r.branch_code, 1, 2)  as group_code,
    g.group_name                  as group_name,

    case
        when g.group_name is null and r.branch_name is null then null
        when g.group_name is null then r.branch_name
        when r.branch_name is null then g.group_name
        else concat(g.group_name, ' / ', r.branch_name)
    end                          as branch_full_name,

    r._ingestion_date,
    r._source_file_name,
    r._extras

from ramo r
left join {{ ref('dim_grupo') }} g
    on substr(r.branch_code, 1, 2) = g.group_code
