"""Thin GCS object I/O for the data pipeline (raw zips + bronze parquet).

Replaces the handful of boto3/S3 calls the pipeline used, now on GCS — the
single-cloud consolidation (Etapa 2). BigQuery loads parquet straight from
gs:// (see bq_loader), so this is upload + download + URI parsing only.

Auth is ADC: locally your gcloud creds, in CI the ingest SA key (GCP_SA_KEY).
"""

from __future__ import annotations

from pathlib import Path

import google.cloud.storage as storage
import structlog

log = structlog.get_logger(__name__)


def _client() -> storage.Client:
    return storage.Client()


def parse_gcs_uri(uri: str) -> tuple[str, str]:
    """Split ``gs://bucket/key`` into ``(bucket, key)``."""
    if not uri.startswith("gs://"):
        raise ValueError(f"Not a gs:// URI: {uri}")
    bucket, _, key = uri[len("gs://") :].partition("/")
    if not bucket or not key:
        raise ValueError(f"Malformed gs:// URI: {uri}")
    return bucket, key


def upload_file(local_path: Path, bucket: str, key: str) -> str:
    """Upload ``local_path`` to ``gs://bucket/key``. Returns the gs:// URI.

    The GCS client streams large objects in resumable chunks automatically, so
    the ~500 MB raw zip needs no manual multipart handling.
    """
    uri = f"gs://{bucket}/{key}"
    log.info("gcs.upload.start", uri=uri, local=str(local_path))
    _client().bucket(bucket).blob(key).upload_from_filename(str(local_path))
    log.info("gcs.upload.ok", uri=uri)
    return uri


def download_file(gcs_uri: str, dest: Path) -> None:
    """Download ``gs://bucket/key`` to ``dest``."""
    bucket, key = parse_gcs_uri(gcs_uri)
    log.info("gcs.download.start", uri=gcs_uri, dest=str(dest))
    _client().bucket(bucket).blob(key).download_to_filename(str(dest))
    log.info("gcs.download.ok", uri=gcs_uri, bytes=dest.stat().st_size)
