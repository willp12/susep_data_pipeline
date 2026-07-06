import datetime
import decimal
from unittest.mock import MagicMock

import pytest

from src.agent.tools.bq_query import (
    DEFAULT_MAX_BYTES,
    NonReadOnlyQueryError,
    QueryTooExpensiveError,
    run_sql,
)


def _dry_run_job(estimated_bytes: int) -> MagicMock:
    job = MagicMock()
    job.total_bytes_processed = estimated_bytes
    return job


def _result_job(rows: list[dict], *, bytes_processed: int, cache_hit: bool = False) -> MagicMock:
    job = MagicMock()
    job.total_bytes_processed = bytes_processed
    job.cache_hit = cache_hit
    job.job_id = "job-123"
    # Each "row" exposes .items() like a bigquery.Row.
    row_objs = []
    for r in rows:
        row = MagicMock()
        row.items.return_value = r.items()
        row_objs.append(row)
    job.result.return_value = iter(row_objs)
    return job


def test_run_sql_rejects_over_cap_without_executing() -> None:
    client = MagicMock()
    client.query.return_value = _dry_run_job(2 * 1024**3)  # 2 GiB

    with pytest.raises(QueryTooExpensiveError) as exc:
        run_sql("SELECT * FROM big_table", client=client)

    assert exc.value.estimated_bytes == 2 * 1024**3
    assert exc.value.max_bytes == DEFAULT_MAX_BYTES
    # Only the dry-run call happened — no real execution.
    assert client.query.call_count == 1


def test_run_sql_happy_path_returns_rows_and_metadata() -> None:
    client = MagicMock()
    client.query.side_effect = [
        _dry_run_job(1024),  # cheap dry-run
        _result_job([{"ramo": "auto", "premio": 100}], bytes_processed=1024),
    ]

    result = run_sql("SELECT ramo, premio FROM t", client=client)

    assert result["row_count"] == 1
    assert result["rows"] == [{"ramo": "auto", "premio": 100}]
    assert result["bytes_estimated"] == 1024
    assert result["bytes_processed"] == 1024
    assert result["cache_hit"] is False
    assert result["job_id"] == "job-123"
    assert client.query.call_count == 2


def test_run_sql_coerces_non_json_types() -> None:
    client = MagicMock()
    client.query.side_effect = [
        _dry_run_job(512),
        _result_job(
            [{"d": datetime.date(2026, 5, 20), "v": decimal.Decimal("1.50")}],
            bytes_processed=512,
        ),
    ]

    result = run_sql("SELECT d, v FROM t", client=client)

    assert result["rows"] == [{"d": "2026-05-20", "v": 1.5}]


def test_run_sql_respects_custom_cap() -> None:
    client = MagicMock()
    client.query.return_value = _dry_run_job(300 * 1024**2)  # 300 MiB

    with pytest.raises(QueryTooExpensiveError):
        run_sql("SELECT * FROM t", max_bytes=256 * 1024**2, client=client)


@pytest.mark.parametrize(
    "sql",
    [
        "EXPORT DATA OPTIONS(uri='gs://b/*.csv') AS SELECT 1",
        "SELECT 1; EXPORT DATA OPTIONS(uri='gs://b/*') AS SELECT 2",
        "EXECUTE IMMEDIATE 'SELECT 1'",
        "DELETE FROM t WHERE 1=1",
        "DROP TABLE t",
        "CREATE TABLE t AS SELECT 1",
        "INSERT INTO t VALUES (1)",
        "SELECT 1; DROP TABLE t",
        "/* c */ EXPORT/**/DATA OPTIONS(uri='gs://b') AS SELECT 1",  # comment evasion
        "   ",
    ],
)
def test_run_sql_rejects_non_readonly_without_executing(sql: str) -> None:
    client = MagicMock()
    with pytest.raises(NonReadOnlyQueryError):
        run_sql(sql, client=client)
    # Rejected by the shape guard before any BigQuery call (not even a dry-run).
    assert client.query.call_count == 0


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "select ramo from t",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "  SELECT 1  ;  ",  # trailing semicolon is fine
        "(SELECT 1) UNION ALL (SELECT 2)",
        "SELECT 'DROP TABLE t' AS note",  # keyword only inside a string literal
    ],
)
def test_run_sql_allows_readonly_queries(sql: str) -> None:
    client = MagicMock()
    client.query.side_effect = [_dry_run_job(10), _result_job([{"a": 1}], bytes_processed=10)]
    result = run_sql(sql, client=client)
    assert result["row_count"] == 1
    assert client.query.call_count == 2
