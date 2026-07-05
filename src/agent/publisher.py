"""Publish agent outputs to the GCS reports bucket — the source of truth.

Layout in the bucket (see bootstrap 04):

    manifest.json                      # index: one entry per published run
    reports/2026/2026-06-09.md         # analysis only
    queries/2026/2026-06-09.sql.md     # SQL appendix
    logs/2026/2026-06-09.jsonl         # structured run log

The manifest carries the insight titles of every report, so building the
history digest costs one small GET instead of downloading every report.
There is exactly one writer (the single agent run), so plain
read-modify-write on the manifest is safe.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from typing import Any

# google-cloud-storage ships no py.typed marker; importing the submodule
# directly lets mypy fall back to ignore_missing_imports in every env.
import google.cloud.storage as storage
import structlog

from src.config import get_settings

log = structlog.get_logger(__name__)

MANIFEST_PATH = "manifest.json"

_TITLE_RE = re.compile(r"^###\s+(.+)$", re.MULTILINE)

# The report body declares its mode in the executive summary, e.g.
# "Modo: deep-dive" or "**Modo: novo ângulo.**" (formatting varies by run).
_MODE_RE = re.compile(r"\bmodo\b[:\s*]+([^\n]+)", re.IGNORECASE)


class ReportStore:
    """Thin wrapper over the GCS bucket holding the published reports."""

    def __init__(
        self,
        bucket_name: str | None = None,
        client: storage.Client | None = None,
    ) -> None:
        settings = get_settings()
        self.bucket_name = bucket_name or settings.gcp_reports_bucket
        if not self.bucket_name:
            raise RuntimeError(
                "Reports bucket not configured — set GCP_PROJECT_ID (or "
                "GCP_REPORTS_BUCKET) in .env and run scripts/bootstrap/04_gcp_gcs_reports.sh."
            )
        self._client = client or storage.Client(project=settings.gcp_project_id or None)
        self._bucket = self._client.bucket(self.bucket_name)

    def exists(self, path: str) -> bool:
        return bool(self._bucket.blob(path).exists())

    def download_text(self, path: str) -> str:
        return str(self._bucket.blob(path).download_as_text())

    def upload_text(self, path: str, text: str, content_type: str = "text/markdown") -> None:
        self._bucket.blob(path).upload_from_string(text, content_type=content_type)

    def load_manifest(self) -> dict[str, Any]:
        if not self.exists(MANIFEST_PATH):
            return {"reports": []}
        return dict(json.loads(self.download_text(MANIFEST_PATH)))

    def save_manifest(self, manifest: dict[str, Any]) -> None:
        self.upload_text(
            MANIFEST_PATH,
            json.dumps(manifest, ensure_ascii=False, indent=2),
            content_type="application/json",
        )


def report_path(stem: str) -> str:
    return f"reports/{stem[:4]}/{stem}.md"


def queries_path(stem: str) -> str:
    return f"queries/{stem[:4]}/{stem}.sql.md"


def log_path(stem: str) -> str:
    return f"logs/{stem[:4]}/{stem}.jsonl"


def extract_titles(body: str) -> list[str]:
    """Insight titles (### headers) of a report body, for the manifest."""
    return [t.strip() for t in _TITLE_RE.findall(body)]


def extract_mode(body: str) -> str | None:
    """Normalized run mode declared in the body: 'deep-dive' | 'novo ângulo'.

    Recorded in the manifest so the next run can alternate deterministically
    (see history.next_mode). None when the body declares no mode (old reports).
    """
    match = _MODE_RE.search(body)
    if not match:
        return None
    return "deep-dive" if "deep" in match.group(1).lower() else "novo ângulo"


def reserve_stem(report_date: date, manifest: dict[str, Any]) -> str:
    """Pick the next non-clobbering stem for the date, against the manifest.

    Mirrors the old filesystem rule: first run of a day is `YYYY-MM-DD`,
    same-day reruns get `_2`, `_3`, … The manifest (not the local fs, which is
    ephemeral in CI) is what knows which stems already exist.
    """
    taken = {entry["stem"] for entry in manifest.get("reports", [])}
    base = report_date.isoformat()
    stem = base
    suffix = 2
    while stem in taken:
        stem = f"{base}_{suffix}"
        suffix += 1
    return stem


def publish_run(
    store: ReportStore,
    *,
    stem: str,
    report_date: date,
    report_text: str,
    body: str,
    queries_text: str | None,
    log_lines: list[str] | None,
    model: str,
    cost_usd: float | None,
    queries_run: int,
) -> dict[str, Any]:
    """Upload the run artifacts and append the manifest entry.

    Returns the manifest entry. The manifest is re-read here (not reused from
    reserve time) to keep the read-modify-write window minimal.
    """
    entry: dict[str, Any] = {
        "stem": stem,
        "date": report_date.isoformat(),
        "report_path": report_path(stem),
        "queries_path": queries_path(stem) if queries_text else None,
        "log_path": log_path(stem) if log_lines else None,
        "titles": extract_titles(body),
        "mode": extract_mode(body),
        "model": model,
        "cost_usd": cost_usd,
        "queries_run": queries_run,
        "published_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }

    store.upload_text(entry["report_path"], report_text)
    if queries_text:
        store.upload_text(entry["queries_path"], queries_text)
    if log_lines:
        store.upload_text(
            entry["log_path"],
            "\n".join(log_lines) + "\n",
            content_type="application/jsonl",
        )

    manifest = store.load_manifest()
    manifest.setdefault("reports", []).append(entry)
    store.save_manifest(manifest)

    log.info(
        "agent.publish.ok",
        bucket=store.bucket_name,
        report_path=entry["report_path"],
        queries_path=entry["queries_path"],
        log_path=entry["log_path"],
    )
    return entry
