import json
from typing import Any
from unittest.mock import MagicMock

from evals.precisao.tools import ArmTools

_GIB = 1024**3
DATASETS = ("susep_ses_bronze", "susep_ses_staging", "susep_ses_marts")


def _tools(client: MagicMock, **kwargs: Any) -> ArmTools:
    return ArmTools(
        allowed_dataset="susep_ses_bronze", known_datasets=DATASETS, client=client, **kwargs
    )


def _text(result: dict[str, Any]) -> str:
    return str(result["content"][0]["text"])


def _dry_run_job(estimated_bytes: int) -> MagicMock:
    job = MagicMock()
    job.total_bytes_processed = estimated_bytes
    return job


def _result_job(rows: list[dict[str, Any]], *, bytes_processed: int) -> MagicMock:
    job = MagicMock()
    job.total_bytes_processed = bytes_processed
    job.cache_hit = False
    job.job_id = "job-1"
    row_objs = []
    for r in rows:
        row = MagicMock()
        row.items.return_value = r.items()
        row_objs.append(row)
    job.result.return_value = iter(row_objs)
    return job


def test_queries_on_another_layer_are_blocked() -> None:
    tools = _tools(MagicMock())
    assert tools.blocked_reason("SELECT 1 FROM susep_ses_marts.fct_seguros") is not None
    assert tools.blocked_reason("SELECT 1 FROM `p.SUSEP_SES_STAGING.stg`") is not None
    assert tools.blocked_reason("SELECT * FROM `region-us`.INFORMATION_SCHEMA.TABLES") is not None
    assert tools.blocked_reason("SELECT 1 FROM susep_ses_bronze.ses_seguros") is None
    # A name that merely starts with another dataset's name is not that dataset.
    assert tools.blocked_reason("SELECT 1 FROM susep_ses_marts_backup.t") is None


def test_blocked_query_never_reaches_bigquery() -> None:
    client = MagicMock()
    tools = _tools(client)

    result = tools.sql({"sql": "SELECT SUM(premio_direto) FROM susep_ses_marts.fct_seguros"})

    assert result["is_error"] is True
    client.query.assert_not_called()
    assert tools.log.queries[0].status == "blocked"


def test_describe_drops_column_and_table_descriptions() -> None:
    client = MagicMock()
    field = MagicMock()
    field.name, field.field_type, field.mode = "premio_direto", "STRING", "NULLABLE"
    field.description = "Direct written premium"
    table = MagicMock()
    table.schema = [field]
    table.time_partitioning = None
    table.num_rows, table.num_bytes, table.clustering_fields = 10, 100, None
    table.description = "raw bronze"
    client.get_table.return_value = table

    payload = json.loads(
        _text(_tools(client).describe({"dataset": "susep_ses_bronze", "table": "t"}))
    )

    assert payload["columns"] == [{"name": "premio_direto", "type": "STRING", "mode": "NULLABLE"}]
    assert "description" not in payload


def test_describe_and_sample_refuse_another_dataset() -> None:
    client = MagicMock()
    tools = _tools(client)

    described = tools.describe({"dataset": "susep_ses_marts", "table": "fct_seguros"})
    sampled = tools.sample({"dataset": "susep_ses_marts", "table": "fct_seguros", "n": 5})

    assert described["is_error"] is True
    assert sampled["is_error"] is True
    client.get_table.assert_not_called()
    client.list_rows.assert_not_called()


def test_over_the_cap_message_carries_no_hint() -> None:
    client = MagicMock()
    client.query.return_value = _dry_run_job(2 * _GIB)
    tools = _tools(client)

    result = tools.sql({"sql": "SELECT premio_direto FROM susep_ses_bronze.ses_seguros"})

    message = _text(result).lower()
    assert result["is_error"] is True
    assert "_ingestion_date" not in message
    assert "parti" not in message
    assert tools.log.queries[0].status == "rejected"
    assert tools.log.queries[0].bytes_estimated == 2 * _GIB


def test_ok_query_is_logged_and_long_results_are_truncated() -> None:
    client = MagicMock()
    rows = [{"x": 1}, {"x": 2}, {"x": 3}]
    client.query.side_effect = [_dry_run_job(100), _result_job(rows, bytes_processed=100)]
    tools = _tools(client, max_rows=2)

    payload = json.loads(_text(tools.sql({"sql": "SELECT x FROM susep_ses_bronze.t"})))

    assert payload["query_no"] == 1
    assert payload["rows"] == [{"x": 1}, {"x": 2}]
    assert "truncado" in payload
    record = tools.log.queries[0]
    assert (record.status, record.bytes_estimated, record.row_count) == ("ok", 100, 3)
