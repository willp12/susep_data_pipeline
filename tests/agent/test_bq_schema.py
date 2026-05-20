from unittest.mock import MagicMock

from google.cloud import bigquery

from src.agent.tools.bq_schema import describe_table


def _fake_table() -> MagicMock:
    table = MagicMock()
    table.schema = [
        bigquery.SchemaField("file_name", "STRING", mode="NULLABLE", description="source file"),
        bigquery.SchemaField("ingestion_date", "DATE", mode="REQUIRED", description=None),
    ]
    table.num_rows = 42
    table.num_bytes = 4096
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="ingestion_date",
    )
    table.clustering_fields = ["file_name"]
    table.description = "ingestion log"
    return table


def test_describe_table_returns_full_shape() -> None:
    client = MagicMock()
    client.get_table.return_value = _fake_table()

    result = describe_table("susep_ses_bronze", "ingestion_log", client=client)

    assert result["num_rows"] == 42
    assert result["num_bytes"] == 4096
    assert result["description"] == "ingestion log"
    assert result["clustering_fields"] == ["file_name"]
    assert result["partitioning"] == {"type": "DAY", "field": "ingestion_date"}
    assert result["columns"][0] == {
        "name": "file_name",
        "type": "STRING",
        "mode": "NULLABLE",
        "description": "source file",
    }
    assert result["table_id"].endswith("susep_ses_bronze.ingestion_log")


def test_describe_table_handles_no_partitioning() -> None:
    table = _fake_table()
    table.time_partitioning = None
    client = MagicMock()
    client.get_table.return_value = table

    result = describe_table("susep_ses_staging", "stg_ses_seguros", client=client)

    assert result["partitioning"] is None
