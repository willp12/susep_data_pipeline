"""Coerce BigQuery row values into JSON-serialisable Python.

Agent tool results are JSON-encoded before they reach the model, so date,
datetime, Decimal and bytes values (common in the SES tables) have to be
flattened to primitives first.
"""

from __future__ import annotations

import datetime
import decimal
from typing import Any


def _jsonable_value(value: Any) -> Any:
    if isinstance(value, datetime.date | datetime.time):
        # datetime.datetime is a subclass of datetime.date, so it's covered here.
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def jsonable_row(row: Any) -> dict[str, Any]:
    """Turn a BigQuery ``Row`` (anything with ``.items()``) into a plain dict."""
    return {key: _jsonable_value(value) for key, value in row.items()}
