"""Test doubles for the agent modules."""

from __future__ import annotations

from src.agent.publisher import ReportStore


class FakeStore(ReportStore):
    """In-memory ReportStore: overrides the blob I/O, inherits manifest logic."""

    def __init__(self) -> None:
        self.bucket_name = "fake-bucket"
        self.objects: dict[str, str] = {}

    def exists(self, path: str) -> bool:
        return path in self.objects

    def download_text(self, path: str) -> str:
        return self.objects[path]

    def upload_text(self, path: str, text: str, content_type: str = "text/markdown") -> None:
        self.objects[path] = text
