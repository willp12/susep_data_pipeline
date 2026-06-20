"""Raw-ingest step: scrape → download → hash → dedupe → upload to S3 → log.

End-to-end this module owns everything between "what's the current URL?" and
"there's a row in ingestion_log + (maybe) a zip in s3://…/raw/". The bronze
parquet transformation is a separate step.

Dedup contract (two tiers):

  1. Cheap pre-check — the landing page exposes a ``generated_at`` timestamp
     (and period) without downloading. If it matches our last ingest, the dump
     is unchanged and we skip the ~500 MB download entirely.
  2. Authoritative hash — when the timestamp differs or is unknown, we download
     and compare the SHA256 against the last ``status='ingested'`` row. SUSEP
     exposes no trustworthy ETag/Last-Modified, so the bytes are the final word
     (this also catches a same-period regeneration with identical content).

Either tier, on no change, writes a ``'no_change'`` row and skips the S3 upload.

S3 key layout (partitioned by ingestion date, timestamped so repeated
re-ingests of the same day don't clobber each other):

    raw/{YYYY-MM-DD}/{stem}_{YYYYMMDDTHHMMSSZ}.zip

Where ``stem`` is the SUSEP filename without the ``.zip`` suffix (e.g.
``BaseCompleta``).

Intentionally narrow scope for the MVP:

- No ``failed`` status writes. The schema supports it, but a failed run has no
  authoritative file_hash to record, and the REQUIRED column would force us to
  fabricate a placeholder. Failures surface as exceptions + non-zero exit for
  now; we'll revisit when we add alerting.
- Downloads to a ``tempfile.TemporaryDirectory`` so partial files can't leak
  into subsequent runs.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import boto3
import httpx
import structlog

from src.config import get_settings
from src.ingestion.hasher import sha256_file
from src.ingestion.scraper import SUSEP_SSL_CONTEXT, LatestZipInfo, get_latest_zip_info
from src.state.ingestion_log import get_latest_ingested_metadata, insert_entry

_UNKNOWN = "unknown"  # scraper's sentinel when the landing-page span is missing


def _clean(value: str) -> str | None:
    """Normalise the scraper's 'unknown' sentinel to None for storage."""
    return None if value == _UNKNOWN else value


log = structlog.get_logger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_DOWNLOAD_HEADERS = {"User-Agent": _USER_AGENT}
# Generous read timeout: the SUSEP zip is ~500 MB and their server is slow.
_DOWNLOAD_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)
_STREAM_CHUNK_SIZE = 1024 * 1024  # 1 MiB
_MIN_ACCEPTABLE_BYTES = 1 * 1024 * 1024  # 1 MiB — sanity guard against HTML error pages


def stream_download_to_file(url: str, dest: Path) -> int:
    """Stream ``url`` to ``dest``; return bytes written. Raises on tiny payloads."""
    log.info("downloader.stream.start", url=url, dest=str(dest))
    bytes_written = 0
    with (
        httpx.stream(
            "GET",
            url,
            headers=_DOWNLOAD_HEADERS,
            timeout=_DOWNLOAD_TIMEOUT,
            follow_redirects=True,
            verify=SUSEP_SSL_CONTEXT,
        ) as resp,
        dest.open("wb") as fh,
    ):
        resp.raise_for_status()
        for chunk in resp.iter_bytes(chunk_size=_STREAM_CHUNK_SIZE):
            fh.write(chunk)
            bytes_written += len(chunk)

    if bytes_written < _MIN_ACCEPTABLE_BYTES:
        raise RuntimeError(
            f"Downloaded payload from {url} is only {bytes_written} bytes "
            f"(< {_MIN_ACCEPTABLE_BYTES}); likely an HTML error page, not the zip."
        )

    log.info("downloader.stream.ok", url=url, bytes=bytes_written)
    return bytes_written


def upload_file_to_s3(local_path: Path, bucket: str, key: str) -> str:
    """Upload ``local_path`` to ``s3://bucket/key``. Returns the s3:// URI.

    ``boto3``'s ``upload_file`` automatically uses a multipart transfer above
    its threshold (default 8 MiB), which is exactly what we want for a 500 MB
    zip — no manual chunking needed.
    """
    uri = f"s3://{bucket}/{key}"
    log.info("downloader.s3.upload.start", uri=uri, local=str(local_path))
    client = boto3.client("s3")
    client.upload_file(str(local_path), bucket, key)
    log.info("downloader.s3.upload.ok", uri=uri)
    return uri


def _build_s3_key(filename: str, run_ts: datetime) -> str:
    stem = Path(filename).stem or "BaseCompleta"
    date_part = run_ts.strftime("%Y-%m-%d")
    ts_part = run_ts.strftime("%Y%m%dT%H%M%SZ")
    return f"raw/{date_part}/{stem}_{ts_part}.zip"


def run_raw_ingest() -> dict[str, str]:
    """Full raw-ingest flow. Returns a summary dict for the CLI/tests."""
    settings = get_settings()
    if not settings.gcp_project_id:
        raise RuntimeError(
            "GCP_PROJECT_ID not set — populate .env (see .env.example) before running."
        )

    run_ts = datetime.now(UTC)
    info: LatestZipInfo = get_latest_zip_info()
    previous = get_latest_ingested_metadata(info.filename)
    period = _clean(info.period)
    generated_at = _clean(info.generated_at)

    # Tier 1 (cheap): if the landing page reports the same generation timestamp
    # as our last ingest, the dump hasn't changed — skip the ~500 MB download.
    # Only trust a known timestamp; "unknown" falls through to the hash check.
    if previous is not None and generated_at is not None and previous.generated_at == generated_at:
        log.info(
            "downloader.no_change.precheck",
            file=info.filename,
            generated_at=generated_at,
            period=period,
        )
        insert_entry(
            file_name=info.filename,
            file_hash=previous.file_hash,  # carry forward — content is unchanged
            source_url=info.url,
            status="no_change",
            period=period,
            generated_at=generated_at,
            run_timestamp=run_ts,
        )
        return {
            "status": "no_change",
            "file_name": info.filename,
            "file_hash": previous.file_hash,
            "source_url": info.url,
            "s3_uri": "",
            "period": period or "",
        }

    with tempfile.TemporaryDirectory(prefix="susep-raw-") as tmpdir:
        tmp_path = Path(tmpdir) / info.filename
        bytes_written = stream_download_to_file(info.url, tmp_path)
        file_hash = sha256_file(tmp_path)
        log.info(
            "downloader.hash.ok",
            file=info.filename,
            bytes=bytes_written,
            sha256_prefix=file_hash[:12],
        )

        # Tier 2 (authoritative): the SUSEP page may regenerate with the same
        # period but identical bytes, or expose no timestamp — the content hash
        # is the source of truth.
        if previous is not None and previous.file_hash == file_hash:
            log.info(
                "downloader.no_change",
                file=info.filename,
                sha256_prefix=file_hash[:12],
            )
            insert_entry(
                file_name=info.filename,
                file_hash=file_hash,
                source_url=info.url,
                status="no_change",
                period=period,
                generated_at=generated_at,
                run_timestamp=run_ts,
            )
            return {
                "status": "no_change",
                "file_name": info.filename,
                "file_hash": file_hash,
                "source_url": info.url,
                "s3_uri": "",
            }

        key = _build_s3_key(info.filename, run_ts)
        s3_uri = upload_file_to_s3(tmp_path, settings.aws_s3_bucket, key)

        insert_entry(
            file_name=info.filename,
            file_hash=file_hash,
            source_url=info.url,
            status="ingested",
            period=period,
            generated_at=generated_at,
            run_timestamp=run_ts,
        )
        return {
            "status": "ingested",
            "file_name": info.filename,
            "file_hash": file_hash,
            "source_url": info.url,
            "s3_uri": s3_uri,
            "period": period or "",
        }


def main() -> int:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )
    try:
        result = run_raw_ingest()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("---")
    for k, v in result.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
