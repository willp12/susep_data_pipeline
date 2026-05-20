"""Idempotently provision the BigQuery datasets and ingestion_log table.

Invoked by ``03_gcp_bigquery.sh``. Reads configuration from the environment
(already loaded from ``.env`` by the bash driver).

Never deletes or alters — this script only ensures resources exist with the
expected shape. Schema migrations must be reviewed and applied manually.

Using the Python SDK instead of the ``bq`` CLI because the bundled ``bq`` in
some gcloud SDK releases ships with an absl/pyglib mismatch that breaks it on
Windows (AttributeError on ``absl.flags.FLAGS``). The Python client is the
future-Terraform-equivalent anyway — each call maps to a
``google_bigquery_dataset`` / ``google_bigquery_table`` resource.
"""

from __future__ import annotations

import os
import sys

from google.api_core.exceptions import NotFound
from google.cloud import bigquery


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        sys.stderr.write(f"[bq] ERROR: env var {name} is not set\n")
        sys.exit(1)
    return value


def _ensure_dataset(
    client: bigquery.Client,
    dataset_id: str,
    *,
    location: str,
    description: str,
) -> None:
    ref = bigquery.DatasetReference(client.project, dataset_id)
    try:
        client.get_dataset(ref)
        print(f"[bq] Dataset {client.project}:{dataset_id} already exists — skipping create.")
        return
    except NotFound:
        pass

    dataset = bigquery.Dataset(ref)
    dataset.location = location
    dataset.description = description
    dataset.labels = {
        "project": "susep-ses-pipeline",
        "env": "dev",
        "managedby": "bootstrap-script",
    }
    client.create_dataset(dataset)
    print(f"[bq] Created dataset {client.project}:{dataset_id} (location={location}).")


def _ensure_ingestion_log(client: bigquery.Client, dataset_id: str) -> None:
    table_id = f"{client.project}.{dataset_id}.ingestion_log"
    try:
        client.get_table(table_id)
        print(f"[bq] Table {table_id} already exists — skipping create (never ALTER/DROP here).")
        return
    except NotFound:
        pass

    schema = [
        bigquery.SchemaField(
            "ingestion_date",
            "DATE",
            mode="REQUIRED",
            description="UTC date the file was ingested (partition key).",
        ),
        bigquery.SchemaField(
            "file_name",
            "STRING",
            mode="REQUIRED",
            description="Source file name (e.g. ses_seguros.csv).",
        ),
        bigquery.SchemaField(
            "file_hash",
            "STRING",
            mode="REQUIRED",
            description="SHA256 of the raw zip.",
        ),
        bigquery.SchemaField(
            "source_url",
            "STRING",
            mode="REQUIRED",
            description="Original download URL scraped from SUSEP.",
        ),
        bigquery.SchemaField(
            "status",
            "STRING",
            mode="REQUIRED",
            description="'ingested' | 'no_change' | 'failed'.",
        ),
        bigquery.SchemaField(
            "run_timestamp",
            "TIMESTAMP",
            mode="REQUIRED",
            description="Pipeline run timestamp.",
        ),
    ]

    table = bigquery.Table(table_id, schema=schema)
    table.description = "Ingestion log for susep-ses-pipeline (one row per pipeline run)."
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="ingestion_date",
    )
    table.clustering_fields = ["file_name"]
    table.labels = {
        "project": "susep-ses-pipeline",
        "env": "dev",
        "managedby": "bootstrap-script",
    }

    client.create_table(table)
    print(f"[bq] Created table {table_id} (partitioned by ingestion_date, clustered by file_name).")


def main() -> int:
    project = _env("GCP_PROJECT_ID")
    dataset_bronze = _env("GCP_BQ_DATASET_BRONZE", "susep_ses_bronze")
    dataset_staging = _env("GCP_BQ_DATASET_STAGING", "susep_ses_staging")
    dataset_marts = _env("GCP_BQ_DATASET_MARTS", "susep_ses_marts")
    location = os.environ.get("GCP_BQ_LOCATION", "US")

    client = bigquery.Client(project=project)

    _ensure_dataset(
        client,
        dataset_bronze,
        location=location,
        description="susep-ses-pipeline bronze layer (raw-ish parquet + ingestion_log).",
    )
    _ensure_dataset(
        client,
        dataset_staging,
        location=location,
        description="susep-ses-pipeline dbt staging layer.",
    )
    _ensure_dataset(
        client,
        dataset_marts,
        location=location,
        description="susep-ses-pipeline dbt marts layer (fct/dim — read by the insights agent).",
    )
    _ensure_ingestion_log(client, dataset_bronze)

    print("[bq] BigQuery resources converged OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
