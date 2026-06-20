"""Grant the ingestion service account WRITER on the SUSEP datasets.

Dataset-level access (not project-level) keeps least privilege: this project
also hosts unrelated datasets, so we only give the ingest SA write on bronze,
staging and marts. ``WRITER`` is the dataset-ACL equivalent of
``roles/bigquery.dataEditor`` — enough for the bronze load and ``dbt build``
to create/replace tables. ``jobUser`` (project-level) is granted by the shell
wrapper via gcloud.

Idempotent: adds the access entry only if absent; never removes entries.
Driven by env: GCP_PROJECT_ID, INGEST_SA_EMAIL, and the three dataset names
(defaults match the bootstrap).
"""

from __future__ import annotations

import os
import sys

from google.cloud import bigquery

_ROLE = "WRITER"  # dataset-ACL alias for roles/bigquery.dataEditor


def _ensure_writer(client: bigquery.Client, dataset_name: str, sa_email: str) -> None:
    dataset = client.get_dataset(f"{client.project}.{dataset_name}")
    for entry in dataset.access_entries:
        if (
            entry.entity_type == "userByEmail"
            and entry.entity_id == sa_email
            and entry.role == _ROLE
        ):
            print(f"[ingest-sa] {dataset_name}: {sa_email} already WRITER — skipping.")
            return
    dataset.access_entries = [
        *dataset.access_entries,
        bigquery.AccessEntry(role=_ROLE, entity_type="userByEmail", entity_id=sa_email),
    ]
    client.update_dataset(dataset, ["access_entries"])
    print(f"[ingest-sa] {dataset_name}: granted WRITER to {sa_email}.")


def main() -> int:
    project = os.environ.get("GCP_PROJECT_ID", "")
    sa_email = os.environ.get("INGEST_SA_EMAIL", "")
    if not project or not sa_email:
        print("ERROR: GCP_PROJECT_ID and INGEST_SA_EMAIL must be set.", file=sys.stderr)
        return 1

    datasets = [
        os.environ.get("GCP_BQ_DATASET_BRONZE", "susep_ses_bronze"),
        os.environ.get("GCP_BQ_DATASET_STAGING", "susep_ses_staging"),
        os.environ.get("GCP_BQ_DATASET_MARTS", "susep_ses_marts"),
    ]
    client = bigquery.Client(project=project)
    for dataset_name in datasets:
        _ensure_writer(client, dataset_name, sa_email)
    print("[ingest-sa] Dataset access converged OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
