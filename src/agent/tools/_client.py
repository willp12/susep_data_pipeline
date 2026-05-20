"""Shared BigQuery client for the agent tools.

Auth resolves via Application Default Credentials:
  - locally:  `gcloud auth application-default login`
  - in CI:    Workload Identity Federation (see .github/workflows/insights.yml)

The client is cached so repeated tool calls in a single agent run reuse one
connection. Tools accept an optional ``client`` arg so tests can inject a mock.
"""

from __future__ import annotations

from functools import lru_cache

from google.cloud import bigquery

from src.config import get_settings


@lru_cache(maxsize=1)
def get_client() -> bigquery.Client:
    """Return a cached, project-scoped BigQuery client."""
    settings = get_settings()
    if not settings.gcp_project_id:
        raise RuntimeError("GCP_PROJECT_ID not set — populate .env first.")
    return bigquery.Client(project=settings.gcp_project_id)
