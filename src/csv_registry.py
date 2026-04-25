"""Declarative registry of every CSV we pull out of the SUSEP zip.

One ``CsvSpec`` per file. Adding another CSV to the pipeline = appending one
entry here + generating a ``stg_<name>.sql`` model in dbt. No changes to
``bronze/``, ``loaders/``, or ``main.py``.

Shape comes from what the bronze/load/staging chain actually needs:

- ``csv_name``: exact, case-sensitive — the zip ships mixed case (``Ses_*``,
  ``SES_*``, ``ses_*``). Case is resolved at lookup time with no fallback on
  purpose: if SUSEP changes capitalisation between releases, we want to
  notice (the ``bronze.unzip_to_parquet`` error lists every entry in the zip
  so debugging is a one-liner).

- ``table_name``: snake_case, lowercase. Also the S3 prefix under
  ``bronze/``. Normalising here means the rest of the pipeline doesn't need
  to know the original filename.

- ``load_mode``:
    - ``append_partition`` — fact-style, partitioned by ``_ingestion_date``,
      clustered by ``cluster_by``. Idempotent by deleting the day's partition
      before a WRITE_APPEND. Used by monthly SUSEP dumps (e.g.
      ``Ses_seguros``).
    - ``truncate_replace`` — reference/dimension data. WRITE_TRUNCATE every
      run; no partitioning, no clustering. ``_ingestion_date`` still stamped
      as a regular column for provenance.

- ``expected_columns``: the schema contract. The bronze pass compares actual
  columns against this tuple; missing columns are filled with NULL and extras
  are collapsed into a ``_extras`` JSON string (see
  ``src.ingestion.schema_contract``).

Note on clustering: only makes sense under ``append_partition``. Leave
``cluster_by`` empty (default) for ``truncate_replace`` specs — the loader
ignores it in that mode anyway, but keeping it empty documents intent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LoadMode = Literal["append_partition", "truncate_replace"]


@dataclass(frozen=True)
class CsvSpec:
    """All the knobs a single CSV needs through the bronze + load chain."""

    csv_name: str
    table_name: str
    load_mode: LoadMode
    expected_columns: tuple[str, ...]
    separator: str = ";"
    encoding: str = "latin-1"
    cluster_by: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Column tuples — captured by reading the actual CSV headers out of the SUSEP
# zip (see ``scripts/ck22_inspect_headers.py`` git history for the inspector).
#
# Casing is **literal** to what SUSEP ships, even when it's inconsistent across
# files (``coenti`` in Ses_seguros vs ``Coenti`` in Ses_cias vs ``GRAID`` in
# ses_gruposramos). The schema contract treats this as the source of truth;
# normalisation to a consistent snake_case is the dbt staging layer's job.
# ---------------------------------------------------------------------------

# Ses_seguros.csv — 21 columns, captured from the Ck 6 bronze parquet.
_SES_SEGUROS_COLUMNS: tuple[str, ...] = (
    "damesano",
    "coenti",
    "cogrupo",
    "coramo",
    "premio_direto",
    "premio_de_seguros",
    "premio_retido",
    "premio_ganho",
    "sinistro_direto",
    "sinistro_retido",
    "desp_com",
    "premio_emitido2",
    "premio_emitido_cap",
    "despesa_resseguros",
    "sinistro_ocorrido",
    "receita_resseguro",
    "sinistros_ocorridos_cap",
    "recuperacao_sinistros_ocorridos_cap",
    "rvne",
    "conveniodpvat",
    "consorciosefundos",
)

# Ses_ramos.csv — 2 columns. Reference table mapping ``coramo`` -> ramo name.
_SES_RAMOS_COLUMNS: tuple[str, ...] = (
    "coramo",
    "noramo",
)

# ses_gruposramos.csv — 3 columns. Reference table for grupos de ramos.
# UPPERCASE casing is literal from the SUSEP header.
_SES_GRUPOSRAMOS_COLUMNS: tuple[str, ...] = (
    "GRAID",
    "GRANOME",
    "GRACODIGO",
)

# Ses_cias.csv — 4 columns. Reference table mapping ``Coenti`` -> seguradora.
# Capitalised casing is literal from the SUSEP header.
_SES_CIAS_COLUMNS: tuple[str, ...] = (
    "Coenti",
    "Noenti",
    "Cogrupo",
    "Nogrupo",
)


REGISTRY: tuple[CsvSpec, ...] = (
    CsvSpec(
        csv_name="Ses_seguros.csv",
        table_name="ses_seguros",
        load_mode="append_partition",
        expected_columns=_SES_SEGUROS_COLUMNS,
        cluster_by=("coenti",),
    ),
    CsvSpec(
        csv_name="Ses_ramos.csv",
        table_name="ses_ramos",
        load_mode="truncate_replace",
        expected_columns=_SES_RAMOS_COLUMNS,
    ),
    CsvSpec(
        csv_name="ses_gruposramos.csv",
        table_name="ses_gruposramos",
        load_mode="truncate_replace",
        expected_columns=_SES_GRUPOSRAMOS_COLUMNS,
    ),
    CsvSpec(
        csv_name="Ses_cias.csv",
        table_name="ses_cias",
        load_mode="truncate_replace",
        expected_columns=_SES_CIAS_COLUMNS,
    ),
)


def get_spec(table_name: str) -> CsvSpec:
    """Return the spec for ``table_name`` or raise ``KeyError``."""
    for spec in REGISTRY:
        if spec.table_name == table_name:
            return spec
    raise KeyError(f"No spec registered for table '{table_name}'")
