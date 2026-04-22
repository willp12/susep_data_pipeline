{# Cast a Brazilian-formatted numeric string ("108252392,92") to NUMERIC.

   SUSEP exports use ',' as the decimal separator and, in the sample we've
   inspected, no thousand separator — so a single REPLACE is enough. If we
   later find a file with '.' as thousand separator, extend this macro (one
   place to change) rather than patching every column in the staging model.

   SAFE_CAST returns NULL on parse failure; we prefer that to a failed build
   because bronze is the raw-ish string-typed layer and garbage data should
   surface as NULLs that dbt tests can flag.
#}
{% macro br_to_numeric(col) %}
    safe_cast(replace({{ col }}, ',', '.') as numeric)
{% endmacro %}
