from pathlib import Path
from typing import Any

import pytest

import src.storage.gcs as gcs


@pytest.mark.parametrize(
    ("uri", "bucket", "key"),
    [
        ("gs://b/raw/2026-06/x.zip", "b", "raw/2026-06/x.zip"),
        ("gs://bucket/k", "bucket", "k"),
    ],
)
def test_parse_gcs_uri_ok(uri: str, bucket: str, key: str) -> None:
    assert gcs.parse_gcs_uri(uri) == (bucket, key)


@pytest.mark.parametrize("bad", ["s3://b/k", "gs://b", "gs://", "not-a-uri"])
def test_parse_gcs_uri_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        gcs.parse_gcs_uri(bad)


class _FakeBlob:
    def __init__(self, sink: dict[str, Any]) -> None:
        self._sink = sink

    def upload_from_filename(self, path: str) -> None:
        self._sink["uploaded"] = path

    def download_to_filename(self, path: str) -> None:
        Path(path).write_bytes(b"data")
        self._sink["downloaded_to"] = path


class _FakeBucket:
    def __init__(self, name: str, sink: dict[str, Any]) -> None:
        sink["bucket"] = name
        self._sink = sink

    def blob(self, key: str) -> _FakeBlob:
        self._sink["key"] = key
        return _FakeBlob(self._sink)


def test_upload_file_returns_uri(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sink: dict[str, Any] = {}
    monkeypatch.setattr(
        gcs, "_client", lambda: type("C", (), {"bucket": lambda self, n: _FakeBucket(n, sink)})()
    )
    local = tmp_path / "f.parquet"
    local.write_bytes(b"x")
    uri = gcs.upload_file(local, "mybucket", "bronze/f.parquet")
    assert uri == "gs://mybucket/bronze/f.parquet"
    assert sink["bucket"] == "mybucket"
    assert sink["key"] == "bronze/f.parquet"


def test_download_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sink: dict[str, Any] = {}
    monkeypatch.setattr(
        gcs, "_client", lambda: type("C", (), {"bucket": lambda self, n: _FakeBucket(n, sink)})()
    )
    dest = tmp_path / "out.zip"
    gcs.download_file("gs://b/raw/x.zip", dest)
    assert dest.read_bytes() == b"data"
    assert sink["bucket"] == "b"
    assert sink["key"] == "raw/x.zip"
