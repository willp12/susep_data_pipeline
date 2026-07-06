"""One-off backfill: upload the repo's committed reports to the GCS bucket.

Usage (after provisioning the reports bucket with 'cd infra && terraform apply'):

    uv run python scripts/backfill_reports_to_gcs.py [--reports-dir reports]

Idempotent: stems already present in the manifest are skipped. Old reports are
uploaded as-is (their SQL stays inline in <details> blocks — no appendix), so
`read_report` keeps returning the numbers *and* the SQL behind them.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from src.agent.publisher import MANIFEST_PATH, ReportStore, extract_titles, report_path

_STEM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:_\d+)?$")
_FRONTMATTER_RE = re.compile(r"\A---\n(?P<fm>.*?)\n---\n", re.DOTALL)


def _frontmatter_field(text: str, key: str) -> str | None:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None
    for line in match.group("fm").splitlines():
        if line.startswith(f"{key}:"):
            value = line.split(":", 1)[1].strip()
            return None if value in {"", "null"} else value
    return None


def backfill(reports_dir: Path, store: ReportStore) -> int:
    manifest = store.load_manifest()
    known = {entry["stem"] for entry in manifest.get("reports", [])}

    files = sorted(p for p in reports_dir.glob("*.md") if _STEM_RE.match(p.stem))
    if not files:
        print(f"No date-stemmed reports under {reports_dir} — nothing to do.")
        return 0

    added = 0
    for path in files:
        if path.stem in known:
            print(f"skip {path.stem} (already in manifest)")
            continue
        text = path.read_text(encoding="utf-8")
        cost_raw = _frontmatter_field(text, "cost_usd")
        queries_raw = _frontmatter_field(text, "queries_run")
        entry: dict[str, Any] = {
            "stem": path.stem,
            "date": _frontmatter_field(text, "date") or path.stem[:10],
            "report_path": report_path(path.stem),
            "queries_path": None,
            "log_path": None,
            "titles": extract_titles(text),
            "model": _frontmatter_field(text, "model"),
            "cost_usd": float(cost_raw) if cost_raw else None,
            "queries_run": int(queries_raw) if queries_raw else None,
            "backfilled": True,
        }
        store.upload_text(entry["report_path"], text)
        manifest.setdefault("reports", []).append(entry)
        added += 1
        print(f"uploaded {path.stem} -> gs://{store.bucket_name}/{entry['report_path']}")

    if added:
        manifest["reports"] = sorted(manifest["reports"], key=lambda e: str(e["stem"]))
        store.save_manifest(manifest)
        print(f"manifest updated ({added} added) -> gs://{store.bucket_name}/{MANIFEST_PATH}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    args = parser.parse_args()
    if not args.reports_dir.is_dir():
        print(f"ERROR: {args.reports_dir} is not a directory", file=sys.stderr)
        return 1
    return backfill(args.reports_dir, ReportStore())


if __name__ == "__main__":
    raise SystemExit(main())
