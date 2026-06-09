"""E-mail delivery of the daily report (Gmail SMTP + app password).

The e-mail is the human review channel now that reports go straight to GCS
instead of a PR: HTML body rendered from the analysis markdown, with the raw
``.md`` of the report and of the SQL appendix attached.

Delivery is best-effort by design: the report is already published when we get
here, so a failed/unconfigured send logs loudly but never fails the run.
Configure via env (see .env.example): SMTP_USERNAME + SMTP_APP_PASSWORD +
REPORT_EMAIL_TO. With Gmail, the app password requires 2FA on the account.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

import markdown
import structlog

from src.config import Settings, get_settings

log = structlog.get_logger(__name__)


def is_configured(settings: Settings) -> bool:
    return bool(settings.smtp_username and settings.smtp_app_password and settings.report_email_to)


def render_html(body: str, stem: str) -> str:
    inner = markdown.markdown(body, extensions=["tables", "fenced_code"])
    return (
        '<html><body style="font-family: sans-serif; max-width: 720px;">'
        f"<h1>Insights SUSEP SES — {stem}</h1>{inner}"
        "</body></html>"
    )


def build_message(
    *,
    stem: str,
    body: str,
    report_text: str,
    queries_text: str | None,
    sender: str,
    to: str,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"Insights SUSEP SES — {stem}"
    msg["From"] = sender
    msg["To"] = to
    # Plain-text fallback is the raw markdown; the HTML part is preferred.
    msg.set_content(body)
    msg.add_alternative(render_html(body, stem), subtype="html")
    msg.add_attachment(
        report_text.encode("utf-8"),
        maintype="text",
        subtype="markdown",
        filename=f"{stem}.md",
    )
    if queries_text:
        msg.add_attachment(
            queries_text.encode("utf-8"),
            maintype="text",
            subtype="markdown",
            filename=f"{stem}.sql.md",
        )
    return msg


def send_report(
    *,
    stem: str,
    body: str,
    report_text: str,
    queries_text: str | None,
) -> str:
    """Send the report e-mail. Returns 'sent', 'skipped' or 'failed'."""
    settings = get_settings()
    if not is_configured(settings):
        log.warning(
            "agent.email.skipped",
            reason="SMTP_USERNAME / SMTP_APP_PASSWORD / REPORT_EMAIL_TO not all set",
        )
        return "skipped"

    sender = settings.report_email_from or settings.smtp_username
    msg = build_message(
        stem=stem,
        body=body,
        report_text=report_text,
        queries_text=queries_text,
        sender=sender,
        to=settings.report_email_to,
    )
    try:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            smtp.login(settings.smtp_username, settings.smtp_app_password)
            smtp.send_message(msg)
    except Exception as exc:
        # The report is already published; e-mail failure must not fail the run.
        log.error("agent.email.failed", error=str(exc))
        return "failed"

    log.info("agent.email.sent", to=settings.report_email_to, subject=msg["Subject"])
    return "sent"
