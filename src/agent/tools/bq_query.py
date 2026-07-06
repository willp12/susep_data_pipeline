"""run_sql — execute arbitrary read-only SQL with a hard bytes cap.

Cost safety has two layers:
  1. A mandatory dry-run estimates ``total_bytes_processed`` before running.
     If it exceeds ``max_bytes`` we raise ``QueryTooExpensiveError`` and never run
     the real job.
  2. The real job sets ``maximum_bytes_billed`` so BigQuery itself aborts if
     the estimate was somehow wrong (belt and suspenders).

IAM is the primary trust boundary: the agent's service account is read-only
(``bigquery.dataViewer`` + ``bigquery.jobUser``), so DML/DDL fail at execution.
As defense in depth we also require a single ``SELECT``/``WITH`` statement and
reject constructs a read-only role does NOT stop on its own — ``EXPORT DATA``
(needs only ``storage.objects.create``) and ``EXECUTE IMMEDIATE`` (dynamic SQL).
That guard is a shape check on comment/literal-blanked SQL, not a full parser.
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from google.cloud import bigquery

from src.agent.tools._client import get_client
from src.agent.tools._serde import jsonable_row

log = structlog.get_logger(__name__)

_GIB = 1024**3
DEFAULT_MAX_BYTES = 1 * _GIB


class QueryTooExpensiveError(RuntimeError):
    """Raised when the dry-run estimate exceeds the byte cap."""

    def __init__(self, estimated_bytes: int, max_bytes: int) -> None:
        self.estimated_bytes = estimated_bytes
        self.max_bytes = max_bytes
        super().__init__(
            f"Query would process {estimated_bytes / _GIB:.3f} GiB, over the "
            f"{max_bytes / _GIB:.3f} GiB cap. Narrow the scan — add a partition "
            "filter on _ingestion_date or select fewer columns."
        )


# --- Read-only statement guard (defense in depth) ---------------------------
# IAM already blocks DML/DDL, but not EXPORT DATA (only needs objects.create on
# the reports bucket) or EXECUTE IMMEDIATE (dynamic SQL). We blank comments and
# string/identifier literals, then require a single SELECT/WITH statement and
# reject the rest. It's a shape check, not a parser — the SA permissions remain
# the real boundary.
_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_COMMENT_LINE = re.compile(r"(?:--|#)[^\n]*")
_STR_SINGLE = re.compile(r"'(?:[^'\\]|\\.)*'")
_STR_DOUBLE = re.compile(r'"(?:[^"\\]|\\.)*"')
_IDENT_BACKTICK = re.compile(r"`[^`]*`")
_WHITESPACE = re.compile(r"\s+")
_READONLY_PREFIX = re.compile(r"[\s(]*(?:SELECT|WITH)\b")
_FORBIDDEN_KW = re.compile(
    r"\bEXPORT\s+DATA\b|\bEXECUTE\s+IMMEDIATE\b|"
    r"\b(?:INSERT|UPDATE|DELETE|MERGE|CREATE|DROP|ALTER|TRUNCATE|GRANT|REVOKE)\b"
)


class NonReadOnlyQueryError(RuntimeError):
    """Raised when a query isn't a single read-only SELECT/WITH statement."""


def _blanked(sql: str) -> str:
    """Uppercase ``sql`` with comments and string/identifier literals blanked
    out and whitespace collapsed — for the structural guard only, never run."""
    s = _COMMENT_BLOCK.sub(" ", sql)
    s = _COMMENT_LINE.sub(" ", s)
    s = _STR_SINGLE.sub("''", s)
    s = _STR_DOUBLE.sub('""', s)
    s = _IDENT_BACKTICK.sub("``", s)
    return _WHITESPACE.sub(" ", s).strip().upper()


def _assert_read_only(sql: str) -> None:
    """Reject anything that isn't a single read-only SELECT/WITH statement."""
    body = _blanked(sql)
    if body.endswith(";"):
        body = body[:-1].strip()
    if not body:
        raise NonReadOnlyQueryError("Empty query.")
    if ";" in body:
        raise NonReadOnlyQueryError("Only a single statement is allowed (remove the ';').")
    if not _READONLY_PREFIX.match(body):
        raise NonReadOnlyQueryError("Only read-only SELECT / WITH queries are allowed.")
    hit = _FORBIDDEN_KW.search(body)
    if hit:
        raise NonReadOnlyQueryError(
            f"Disallowed keyword for a read-only query: {hit.group(0).strip()}."
        )


def _dry_run_bytes(client: bigquery.Client, sql: str) -> int:
    cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    job = client.query(sql, job_config=cfg)
    return int(job.total_bytes_processed or 0)


def run_sql(
    sql: str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    client: bigquery.Client | None = None,
) -> dict[str, Any]:
    """Run read-only SQL, capped at ``max_bytes`` of data scanned.

    Raises ``QueryTooExpensiveError`` (before executing) if the dry-run estimate is
    over the cap.
    """
    _assert_read_only(sql)
    client = client or get_client()

    estimated = _dry_run_bytes(client, sql)
    if estimated > max_bytes:
        log.warning(
            "agent.tool.run_sql.rejected",
            bytes_estimated=estimated,
            max_bytes=max_bytes,
        )
        raise QueryTooExpensiveError(estimated, max_bytes)

    cfg = bigquery.QueryJobConfig(maximum_bytes_billed=max_bytes)
    job = client.query(sql, job_config=cfg)
    rows = [jsonable_row(row) for row in job.result()]

    result = {
        "rows": rows,
        "row_count": len(rows),
        "bytes_estimated": estimated,
        "bytes_processed": int(job.total_bytes_processed or 0),
        "cache_hit": bool(job.cache_hit),
        "job_id": job.job_id,
    }
    log.info(
        "agent.tool.run_sql.ok",
        row_count=len(rows),
        bytes_processed=result["bytes_processed"],
        cache_hit=result["cache_hit"],
    )
    return result
