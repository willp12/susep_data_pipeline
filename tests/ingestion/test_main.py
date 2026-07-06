"""Tests for the pipeline orchestrator's outcome surfacing (src.main).

The pipeline steps are monkeypatched; these check that run() reports the
right {status, period} and that main() emits GitHub step outputs + fires the
ingest e-mail only on a new period.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import src.main as m


def test_run_short_circuits_on_no_change(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        m, "run_raw_ingest", lambda: {"status": "no_change", "period": "202602", "gcs_uri": ""}
    )
    # Downstream steps must NOT run on no_change.
    monkeypatch.setattr(m, "run_bronze_build", lambda uri: pytest.fail("bronze ran"))

    outcome = m.run()
    assert outcome == {"status": "no_change", "period": "202602"}


def test_run_full_pipeline_on_ingested(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        m,
        "run_raw_ingest",
        lambda: {"status": "ingested", "period": "202603", "gcs_uri": "gs://b/raw/x.zip"},
    )
    monkeypatch.setattr(
        m, "run_bronze_build", lambda uri: calls.append("bronze") or {"bronze_gcs_uri": "gs://b/p"}
    )
    monkeypatch.setattr(m, "run_bronze_load", lambda uri: calls.append("load") or {})
    monkeypatch.setattr(m, "_run_dbt_build", lambda: calls.append("dbt"))

    outcome = m.run()
    assert outcome == {"status": "ingested", "period": "202603"}
    assert calls == ["bronze", "load", "dbt"]


def test_main_emits_github_output_and_notifies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gh_output = tmp_path / "gh_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_output))
    monkeypatch.setattr(m, "run", lambda: {"status": "ingested", "period": "202603"})
    notified: list[str] = []
    monkeypatch.setattr(
        m, "send_ingest_notification", lambda *, period: notified.append(period) or "sent"
    )

    rc = m.main()
    assert rc == 0
    written = gh_output.read_text(encoding="utf-8")
    assert "status=ingested" in written
    assert "period=202603" in written
    assert notified == ["202603"]


def test_main_no_notify_on_no_change(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out.txt"))
    monkeypatch.setattr(m, "run", lambda: {"status": "no_change", "period": ""})
    monkeypatch.setattr(
        m, "send_ingest_notification", lambda **kw: pytest.fail("notified on no_change")
    )

    assert m.main() == 0


def test_main_returns_1_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> dict[str, str]:
        raise RuntimeError("pipeline blew up")

    monkeypatch.setattr(m, "run", boom)
    assert m.main() == 1


def test_emit_github_output_noop_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    # Must not raise when not running under Actions.
    m._emit_github_output({"status": "ingested", "period": "202603"})


def test_emit_github_output_drops_malformed_period(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gh_output = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_output))
    # A scraped period that isn't YYYYMM (here carrying shell metacharacters and
    # a newline that could inject an extra output) must be dropped, not written.
    m._emit_github_output({"status": "ingested", "period": "202604$(whoami)\nstatus=hacked"})
    written = gh_output.read_text(encoding="utf-8")
    assert "status=ingested" in written
    assert "period=\n" in written  # emitted empty
    assert "whoami" not in written
    assert "status=hacked" not in written


def test_emit_github_output_keeps_valid_period(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    gh_output = tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_output))
    m._emit_github_output({"status": "ingested", "period": "202604"})
    assert "period=202604" in gh_output.read_text(encoding="utf-8")
