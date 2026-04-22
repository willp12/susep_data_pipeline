"""Lenient schema contract for SUSEP CSVs.

Philosophy: **never raise**. SUSEP can drop a column, add a column, or rename
one, and the pipeline keeps landing data — with warnings in the log so the
owner finds out at review time instead of on-call.

Rules applied by :func:`apply_schema_contract`:

- **Missing columns** (expected by ``spec`` but absent from the CSV): added
  as an all-null ``pl.String`` column and logged as ``schema.drift.missing``.
- **Extra columns** (present in CSV but not in ``spec.expected_columns``):
  packed into a single ``_extras`` ``pl.String`` column that holds a JSON
  object per row (e.g. ``{"new_col": "value"}``). Logged as
  ``schema.drift.extras``.
- **Exact match**: ``_extras`` is added as an all-null column so every
  downstream BQ table has a stable schema of
  ``expected_columns + [_extras]`` (plus the ``_ingestion_date`` /
  ``_source_file_name`` provenance columns stamped by the bronze step).

``_extras`` is NULL on the exact-match path (not ``'{}'``) to keep BQ
compression efficient and ``WHERE _extras IS NOT NULL`` trivially fast.

Output column order after this function:
``list(spec.expected_columns) + ["_extras"]``. The bronze step adds
``_ingestion_date`` and ``_source_file_name`` after calling us and then does
a final ``.select(...)`` to produce the canonical order.
"""

from __future__ import annotations

import polars as pl
import structlog

from src.csv_registry import CsvSpec

log = structlog.get_logger(__name__)

_EXTRAS_COL = "_extras"


def apply_schema_contract(df: pl.DataFrame, spec: CsvSpec) -> pl.DataFrame:
    """Reshape ``df`` to match ``spec`` lenient-style. See module docstring."""
    actual = list(df.columns)
    expected = list(spec.expected_columns)
    expected_set = set(expected)
    actual_set = set(actual)

    missing = [c for c in expected if c not in actual_set]
    extras = [c for c in actual if c not in expected_set]

    if missing:
        log.warning(
            "schema.drift.missing",
            spec=spec.table_name,
            columns=missing,
            count=len(missing),
        )
        df = df.with_columns([pl.lit(None, dtype=pl.String).alias(col) for col in missing])

    if extras:
        log.warning(
            "schema.drift.extras",
            spec=spec.table_name,
            columns=extras,
            count=len(extras),
        )
        # Pack extras into one JSON-per-row string column, then drop the
        # originals. `struct.json_encode()` emits `{"col": "value", ...}`.
        df = df.with_columns(pl.struct(extras).struct.json_encode().alias(_EXTRAS_COL)).drop(extras)
    else:
        log.info("schema.drift.clean", spec=spec.table_name)
        df = df.with_columns(pl.lit(None, dtype=pl.String).alias(_EXTRAS_COL))

    return df.select([*expected, _EXTRAS_COL])
