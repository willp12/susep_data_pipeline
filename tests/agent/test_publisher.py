from datetime import date

from src.agent.publisher import (
    extract_titles,
    log_path,
    publish_run,
    queries_path,
    report_path,
    reserve_stem,
)
from tests.agent._fakes import FakeStore


def test_paths_are_year_partitioned() -> None:
    assert report_path("2026-06-09") == "reports/2026/2026-06-09.md"
    assert queries_path("2026-06-09_2") == "queries/2026/2026-06-09_2.sql.md"
    assert log_path("2026-06-09") == "logs/2026/2026-06-09.jsonl"


def test_extract_titles() -> None:
    body = "## Insights\n### 1. Primeiro\ntexto\n### 2. Segundo\ntexto\n"
    assert extract_titles(body) == ["1. Primeiro", "2. Segundo"]


def test_reserve_stem_suffixes_same_day_runs() -> None:
    manifest = {"reports": [{"stem": "2026-06-09"}, {"stem": "2026-06-09_2"}]}
    assert reserve_stem(date(2026, 6, 9), manifest) == "2026-06-09_3"
    assert reserve_stem(date(2026, 6, 10), manifest) == "2026-06-10"
    assert reserve_stem(date(2026, 6, 9), {"reports": []}) == "2026-06-09"


def test_publish_run_uploads_artifacts_and_manifest() -> None:
    store = FakeStore()
    entry = publish_run(
        store,
        stem="2026-06-09",
        report_date=date(2026, 6, 9),
        report_text="--- fm ---\ncorpo",
        body="### 1. Achado\ntexto",
        queries_text="## Query 1\nSELECT 1",
        log_lines=['{"event": "x"}'],
        model="sonnet",
        cost_usd=0.42,
        queries_run=3,
    )

    assert store.objects["reports/2026/2026-06-09.md"] == "--- fm ---\ncorpo"
    assert store.objects["queries/2026/2026-06-09.sql.md"] == "## Query 1\nSELECT 1"
    assert store.objects["logs/2026/2026-06-09.jsonl"] == '{"event": "x"}\n'

    manifest = store.load_manifest()
    assert [e["stem"] for e in manifest["reports"]] == ["2026-06-09"]
    assert entry["titles"] == ["1. Achado"]
    assert entry["queries_path"] == "queries/2026/2026-06-09.sql.md"
    assert entry["published_at"]


def test_publish_run_without_queries_or_logs() -> None:
    store = FakeStore()
    entry = publish_run(
        store,
        stem="2026-06-09",
        report_date=date(2026, 6, 9),
        report_text="corpo",
        body="sem insights",
        queries_text=None,
        log_lines=None,
        model="sonnet",
        cost_usd=None,
        queries_run=0,
    )
    assert entry["queries_path"] is None
    assert entry["log_path"] is None
    assert "queries/2026/2026-06-09.sql.md" not in store.objects


def test_publish_run_appends_to_existing_manifest() -> None:
    store = FakeStore()
    for stem in ("2026-06-08", "2026-06-09"):
        publish_run(
            store,
            stem=stem,
            report_date=date.fromisoformat(stem),
            report_text="x",
            body="### 1. T\n",
            queries_text=None,
            log_lines=None,
            model="sonnet",
            cost_usd=None,
            queries_run=0,
        )
    manifest = store.load_manifest()
    assert [e["stem"] for e in manifest["reports"]] == ["2026-06-08", "2026-06-09"]
