"""Tests for the two-tier dedup in run_raw_ingest.

All BQ/S3/HTTP boundaries are monkeypatched, so these exercise the
orchestration (which tier fires, what gets logged, whether the 500 MB
download happens) without touching the network or the warehouse.
"""

from __future__ import annotations

from typing import Any

import pytest

import src.ingestion.downloader as dl
from src.ingestion.scraper import LatestZipInfo
from src.state.ingestion_log import IngestedMetadata


def _info(generated_at: str = "10/03/2026 08:00:00", period: str = "202602") -> LatestZipInfo:
    return LatestZipInfo(
        url="https://susep.example/redarq.asp?arq=BaseCompleta%2ezip",
        filename="BaseCompleta.zip",
        period=period,
        generated_at=generated_at,
    )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch every side-effecting boundary; record calls."""
    calls: dict[str, Any] = {"downloaded": False, "uploaded": False, "entries": []}

    monkeypatch.setattr(
        dl,
        "get_settings",
        lambda: type("S", (), {"gcp_project_id": "proj", "aws_s3_bucket": "bucket"})(),
    )

    def fake_download(url: str, dest: Any) -> int:
        calls["downloaded"] = True
        dest.write_bytes(b"x" * (2 * 1024 * 1024))
        return 2 * 1024 * 1024

    monkeypatch.setattr(dl, "stream_download_to_file", fake_download)
    monkeypatch.setattr(dl, "sha256_file", lambda p: calls.get("new_hash", "HASH_NEW"))
    monkeypatch.setattr(
        dl,
        "upload_file_to_s3",
        lambda p, b, k: calls.__setitem__("uploaded", True) or f"s3://{b}/{k}",
    )

    def fake_insert(**kwargs: Any) -> None:
        calls["entries"].append(kwargs)

    monkeypatch.setattr(dl, "insert_entry", fake_insert)
    return calls


def test_tier1_skips_download_when_generated_at_matches(
    monkeypatch: pytest.MonkeyPatch, harness: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        dl, "get_latest_zip_info", lambda: _info(generated_at="10/03/2026 08:00:00")
    )
    monkeypatch.setattr(
        dl,
        "get_latest_ingested_metadata",
        lambda f: IngestedMetadata(
            file_hash="HASH_OLD", period="202602", generated_at="10/03/2026 08:00:00"
        ),
    )

    result = dl.run_raw_ingest()

    assert result["status"] == "no_change"
    assert harness["downloaded"] is False  # the whole point: no 500 MB pull
    assert harness["uploaded"] is False
    assert result["file_hash"] == "HASH_OLD"  # carried forward
    (entry,) = harness["entries"]
    assert entry["status"] == "no_change"
    assert entry["generated_at"] == "10/03/2026 08:00:00"
    assert entry["period"] == "202602"


def test_tier2_ingests_when_generated_at_differs_and_hash_new(
    monkeypatch: pytest.MonkeyPatch, harness: dict[str, Any]
) -> None:
    monkeypatch.setattr(
        dl,
        "get_latest_zip_info",
        lambda: _info(generated_at="15/03/2026 09:00:00", period="202603"),
    )
    monkeypatch.setattr(
        dl,
        "get_latest_ingested_metadata",
        lambda f: IngestedMetadata(
            file_hash="HASH_OLD", period="202602", generated_at="10/03/2026 08:00:00"
        ),
    )
    harness["new_hash"] = "HASH_NEW"

    result = dl.run_raw_ingest()

    assert result["status"] == "ingested"
    assert harness["downloaded"] is True
    assert harness["uploaded"] is True
    assert result["s3_uri"].startswith("s3://bucket/raw/")
    (entry,) = harness["entries"]
    assert entry["status"] == "ingested"
    assert entry["period"] == "202603"


def test_tier2_no_change_when_regenerated_with_same_bytes(
    monkeypatch: pytest.MonkeyPatch, harness: dict[str, Any]
) -> None:
    # New generated_at (so Tier 1 doesn't skip) but identical content hash.
    monkeypatch.setattr(
        dl, "get_latest_zip_info", lambda: _info(generated_at="15/03/2026 09:00:00")
    )
    monkeypatch.setattr(
        dl,
        "get_latest_ingested_metadata",
        lambda f: IngestedMetadata(
            file_hash="HASH_SAME", period="202602", generated_at="10/03/2026 08:00:00"
        ),
    )
    harness["new_hash"] = "HASH_SAME"

    result = dl.run_raw_ingest()

    assert result["status"] == "no_change"
    assert harness["downloaded"] is True  # had to download to learn this
    assert harness["uploaded"] is False
    assert harness["entries"][0]["status"] == "no_change"


def test_unknown_generated_at_falls_through_to_hash(
    monkeypatch: pytest.MonkeyPatch, harness: dict[str, Any]
) -> None:
    # Page exposed no timestamp — never skip on "unknown"; download and hash.
    monkeypatch.setattr(
        dl, "get_latest_zip_info", lambda: _info(generated_at="unknown", period="unknown")
    )
    monkeypatch.setattr(
        dl,
        "get_latest_ingested_metadata",
        lambda f: IngestedMetadata(file_hash="HASH_OLD", period=None, generated_at=None),
    )
    harness["new_hash"] = "HASH_NEW"

    result = dl.run_raw_ingest()

    assert result["status"] == "ingested"
    assert harness["downloaded"] is True
    # 'unknown' is normalised to NULL in storage.
    assert harness["entries"][0]["generated_at"] is None
    assert harness["entries"][0]["period"] is None


def test_first_ever_run_downloads(monkeypatch: pytest.MonkeyPatch, harness: dict[str, Any]) -> None:
    monkeypatch.setattr(dl, "get_latest_zip_info", lambda: _info())
    monkeypatch.setattr(dl, "get_latest_ingested_metadata", lambda f: None)
    harness["new_hash"] = "HASH_NEW"

    result = dl.run_raw_ingest()

    assert result["status"] == "ingested"
    assert harness["downloaded"] is True
