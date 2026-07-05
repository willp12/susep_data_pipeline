import base64
from typing import Any

import httpx
import pytest

import src.agent.emailer as emailer
from src.config import Settings


def test_render_html_converts_markdown() -> None:
    html = emailer.render_html("## Sumário\n\n**forte** e `código`", "2026-06-09")
    assert "<h2>Sumário</h2>" in html
    assert "<strong>forte</strong>" in html
    assert "Insights SUSEP SES — 2026-06-09" in html


def test_build_payload_has_parts_and_attachments() -> None:
    payload = emailer.build_payload(
        stem="2026-06-09",
        body="## Sumário\ntexto",
        report_text="--- fm ---\ncorpo",
        queries_text="## Query 1\nSELECT 1",
        sender="bot@example.com",
        to="will@example.com",
    )
    assert payload["subject"] == "Insights SUSEP SES — 2026-06-09"
    assert payload["sender"] == {"email": "bot@example.com", "name": "SUSEP Insights"}
    assert payload["to"] == [{"email": "will@example.com"}]
    assert "<h2>Sumário</h2>" in payload["htmlContent"]
    assert payload["textContent"] == "## Sumário\ntexto"
    names = [att["name"] for att in payload["attachment"]]
    # .txt suffix: Brevo rejects .md attachments ("Unsupported file format").
    assert names == ["2026-06-09.md.txt", "2026-06-09.sql.md.txt"]
    decoded = base64.b64decode(payload["attachment"][0]["content"]).decode("utf-8")
    assert decoded == "--- fm ---\ncorpo"


def test_build_payload_without_queries_attachment() -> None:
    payload = emailer.build_payload(
        stem="2026-06-09",
        body="x",
        report_text="x",
        queries_text=None,
        sender="bot@example.com",
        to="will@example.com",
    )
    names = [att["name"] for att in payload["attachment"]]
    assert names == ["2026-06-09.md.txt"]


def test_recipients_supports_comma_separated_list() -> None:
    payload = emailer.build_payload(
        stem="2026-06-09",
        body="x",
        report_text="x",
        queries_text=None,
        sender="bot@example.com",
        to="a@x.com, b@y.com",
    )
    assert payload["to"] == [{"email": "a@x.com"}, {"email": "b@y.com"}]


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "brevo_api_key": "key",
        "report_email_to": "will@example.com",
        "report_email_from": "bot@example.com",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class _FakePost:
    """Captures the httpx.post call and returns a canned response."""

    def __init__(self, response: httpx.Response | None = None) -> None:
        self.response = response or httpx.Response(201, json={"messageId": "1"})
        self.url: str | None = None
        self.json: dict[str, Any] | None = None
        self.headers: dict[str, str] | None = None

    def __call__(
        self,
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        self.url = url
        self.json = json
        self.headers = headers
        return self.response


def test_send_report_skips_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(emailer, "get_settings", lambda: _settings(brevo_api_key=""))
    status = emailer.send_report(stem="2026-06-09", body="x", report_text="x", queries_text=None)
    assert status == "skipped"


def test_send_report_skips_without_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(emailer, "get_settings", lambda: _settings(report_email_from=""))
    status = emailer.send_report(stem="2026-06-09", body="x", report_text="x", queries_text=None)
    assert status == "skipped"


def test_send_report_posts_to_brevo(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakePost()
    monkeypatch.setattr(emailer, "get_settings", lambda: _settings())
    monkeypatch.setattr(emailer.httpx, "post", fake)

    status = emailer.send_report(stem="2026-06-09", body="x", report_text="x", queries_text="q")
    assert status == "sent"
    assert fake.url == emailer._BREVO_URL
    assert fake.headers is not None and fake.headers["api-key"] == "key"
    assert fake.json is not None
    assert fake.json["sender"]["email"] == "bot@example.com"
    assert fake.json["to"] == [{"email": "will@example.com"}]
    assert fake.json["subject"] == "Insights SUSEP SES — 2026-06-09"


def test_send_ingest_notification_builds_and_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakePost()
    monkeypatch.setattr(emailer, "get_settings", lambda: _settings())
    monkeypatch.setattr(emailer.httpx, "post", fake)

    status = emailer.send_ingest_notification(period="202603")
    assert status == "sent"
    assert fake.json is not None
    assert "202603" in fake.json["subject"]
    assert fake.json["to"] == [{"email": "will@example.com"}]
    assert "202603" in fake.json["textContent"]
    assert "attachment" not in fake.json


def test_send_ingest_notification_skips_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(emailer, "get_settings", lambda: _settings(report_email_to=""))
    assert emailer.send_ingest_notification(period="202603") == "skipped"


def test_send_report_failure_is_contained(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(emailer, "get_settings", lambda: _settings())
    monkeypatch.setattr(emailer.httpx, "post", boom)

    status = emailer.send_report(stem="2026-06-09", body="x", report_text="x", queries_text=None)
    assert status == "failed"


def test_send_report_non_2xx_is_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakePost(response=httpx.Response(401, text='{"code":"unauthorized"}'))
    monkeypatch.setattr(emailer, "get_settings", lambda: _settings())
    monkeypatch.setattr(emailer.httpx, "post", fake)

    status = emailer.send_report(stem="2026-06-09", body="x", report_text="x", queries_text=None)
    assert status == "failed"
