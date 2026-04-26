{# Filter clause that scopes a bronze table to its most recent
   ``_ingestion_date`` partition.

   Why: bronze tables loaded as ``append_partition`` accumulate one
   partition per pipeline run (`src/loaders/bq_loader.py:_load_append
   _partition`). A naive `SELECT * FROM bronze.<table>` therefore
   sees N copies of the same data when you re-run main N times — and
   silently inflates every downstream sum / count.

   Staging models for `append_partition` specs should always wrap
   their bronze read with this macro so the rest of the warehouse
   sees a single coherent snapshot. `truncate_replace` specs (where
   each run rewrites bronze in full) don't need it.

   Bronze keeps the historical partitions intact for forensics; this
   macro just filters them out at the staging boundary.

   Usage:

       select ...
       from `{{ env_var('GCP_PROJECT_ID') }}.{{ env_var('GCP_BQ_DATASET_BRONZE') }}.ses_seguros`
       where {{ latest_bronze_partition('ses_seguros') }}

   The ``MAX(_ingestion_date)`` subquery is cheap on partitioned
   tables — BigQuery answers it from partition metadata, not a scan.
#}
{% macro latest_bronze_partition(bronze_table) %}
    _ingestion_date = (
        select max(_ingestion_date)
        from `{{ env_var('GCP_PROJECT_ID') }}.{{ env_var('GCP_BQ_DATASET_BRONZE', 'susep_ses_bronze') }}.{{ bronze_table }}`
    )
{% endmacro %}
