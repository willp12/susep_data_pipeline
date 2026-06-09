from email.message import EmailMessage

import pytest

import src.agent.emailer as emailer
from src.config import Settings


def test_render_html_converts_markdown() -> None:
    html = emailer.render_html("## Sumário\n\n**forte** e `código`", "2026-06-09")
    assert "<h2>Sumário</h2>" in html
    assert "<strong>forte</strong>" in html
    assert "Insights SUSEP SES — 2026-06-09" in html


def test_build_message_has_parts_and_attachments() -> None:
    msg = emailer.build_message(
        stem="2026-06-09",
        body="## Sumário\ntexto",
        report_text="--- fm ---\ncorpo",
        queries_text="## Query 1\nSELECT 1",
        sender="bot@example.com",
        to="will@example.com",
    )
    assert msg["Subject"] == "Insights SUSEP SES — 2026-06-09"
    assert msg["To"] == "will@example.com"
    attachments = [part.get_filename() for part in msg.iter_attachments()]
    assert attachments == ["2026-06-09.md", "2026-06-09.sql.md"]
    html = msg.get_body(preferencelist=("html",))
    assert html is not None


def test_build_message_without_queries_attachment() -> None:
    msg = emailer.build_message(
        stem="2026-06-09",
        body="x",
        report_text="x",
        queries_text=None,
        sender="bot@example.com",
        to="will@example.com",
    )
    attachments = [part.get_filename() for part in msg.iter_attachments()]
    assert attachments == ["2026-06-09.md"]


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "smtp_username": "bot@gmail.com",
        "smtp_app_password": "secret",
        "report_email_to": "will@example.com",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_send_report_skips_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(emailer, "get_settings", lambda: _settings(smtp_app_password=""))
    status = emailer.send_report(stem="2026-06-09", body="x", report_text="x", queries_text=None)
    assert status == "skipped"


def test_send_report_sends_via_smtp_ssl(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, object] = {}

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int = 0) -> None:
            sent["host"] = host
            sent["port"] = port

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def login(self, user: str, password: str) -> None:
            sent["login"] = (user, password)

        def send_message(self, msg: EmailMessage) -> None:
            sent["subject"] = msg["Subject"]
            sent["to"] = msg["To"]

    monkeypatch.setattr(emailer, "get_settings", lambda: _settings())
    monkeypatch.setattr(emailer.smtplib, "SMTP_SSL", FakeSMTP)

    status = emailer.send_report(stem="2026-06-09", body="x", report_text="x", queries_text="q")
    assert status == "sent"
    assert sent["host"] == "smtp.gmail.com"
    assert sent["port"] == 465
    assert sent["login"] == ("bot@gmail.com", "secret")
    assert sent["to"] == "will@example.com"


def test_send_report_failure_is_contained(monkeypatch: pytest.MonkeyPatch) -> None:
    class BoomSMTP:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise OSError("connection refused")

    monkeypatch.setattr(emailer, "get_settings", lambda: _settings())
    monkeypatch.setattr(emailer.smtplib, "SMTP_SSL", BoomSMTP)

    status = emailer.send_report(stem="2026-06-09", body="x", report_text="x", queries_text=None)
    assert status == "failed"
