{#
    Override dbt's default schema naming.

    Default behaviour concatenates target schema + custom schema
    (e.g. `susep_ses_staging_marts`). We want explicit, flat dataset names:
      - models with no `+schema` → the profile's dataset (susep_ses_staging)
      - models with `+schema: susep_ses_marts` → exactly that dataset

    This keeps bronze/staging/marts as clean, separate BigQuery datasets and
    mirrors how a Terraform `google_bigquery_dataset` per layer would look.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
