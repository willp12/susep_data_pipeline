"""E-mail delivery of the daily report (Brevo transactional API).

The e-mail is the human review channel now that reports go straight to GCS
instead of a PR: HTML body rendered from the analysis markdown, with the raw
``.md`` of the report and of the SQL appendix attached.

Delivery is best-effort by design: the report is already published when we get
here, so a failed/unconfigured send logs loudly but never fails the run.
Configure via env (see .env.example): BREVO_API_KEY + REPORT_EMAIL_TO +
REPORT_EMAIL_FROM. The sender address must be verified in Brevo.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
import structlog

from src.config import Settings, get_settings

log = structlog.get_logger(__name__)

_BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def is_configured(settings: Settings) -> bool:
    return bool(settings.brevo_api_key and settings.report_email_to and settings.report_email_from)


def render_html(body: str, stem: str) -> str:
    # Imported lazily so the ingestion pipeline (which only sends the plain
    # text notice) doesn't need the agent group's markdown dependency.
    import markdown

    inner = markdown.markdown(body, extensions=["tables", "fenced_code"])
    return (
        '<html><body style="font-family: sans-serif; max-width: 720px;">'
        f"<h1>Insights SUSEP SES — {stem}</h1>{inner}"
        "</body></html>"
    )


def _recipients(to: str) -> list[dict[str, str]]:
    # REPORT_EMAIL_TO accepts a comma-separated list of addresses.
    return [{"email": addr.strip()} for addr in to.split(",") if addr.strip()]


def _attachment(name: str, text: str) -> dict[str, str]:
    return {"name": name, "content": base64.b64encode(text.encode("utf-8")).decode("ascii")}


def build_payload(
    *,
    stem: str,
    body: str,
    report_text: str,
    queries_text: str | None,
    sender: str,
    to: str,
) -> dict[str, Any]:
    attachments = [_attachment(f"{stem}.md", report_text)]
    if queries_text:
        attachments.append(_attachment(f"{stem}.sql.md", queries_text))
    return {
        "sender": {"email": sender, "name": "SUSEP Insights"},
        "to": _recipients(to),
        "subject": f"Insights SUSEP SES — {stem}",
        "htmlContent": render_html(body, stem),
        # Plain-text fallback is the raw markdown; the HTML part is preferred.
        "textContent": body,
        "attachment": attachments,
    }


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
            reason="BREVO_API_KEY / REPORT_EMAIL_TO / REPORT_EMAIL_FROM not all set",
        )
        return "skipped"

    payload = build_payload(
        stem=stem,
        body=body,
        report_text=report_text,
        queries_text=queries_text,
        sender=settings.report_email_from,
        to=settings.report_email_to,
    )
    return _deliver(payload, settings)


def _deliver(payload: dict[str, Any], settings: Settings) -> str:
    """POST a prepared payload to the Brevo API. Returns 'sent' or 'failed'.

    Best-effort by design: a delivery failure logs loudly but never raises —
    callers treat e-mail as a notification, not a critical path.
    """
    try:
        resp = httpx.post(
            _BREVO_URL,
            json=payload,
            headers={"api-key": settings.brevo_api_key, "accept": "application/json"},
            timeout=30.0,
        )
    except Exception as exc:
        log.error("agent.email.failed", error=str(exc), subject=payload["subject"])
        return "failed"

    # Brevo answers 201 (sent) / 202 (scheduled). Log only the status and a
    # body snippet — never the request headers, which carry the API key.
    if not resp.is_success:
        log.error(
            "agent.email.failed",
            status=resp.status_code,
            body=resp.text[:300],
            subject=payload["subject"],
        )
        return "failed"

    log.info("agent.email.sent", to=payload["to"], subject=payload["subject"])
    return "sent"


def send_ingest_notification(*, period: str) -> str:
    """E-mail a short 'new period ingested' notice. Returns sent/skipped/failed.

    Sent by the ingestion pipeline when a new SUSEP dump goes through; skipped
    when e-mail isn't configured (e.g. local runs), so it's safe to call always.
    """
    settings = get_settings()
    if not is_configured(settings):
        log.warning("agent.email.skipped", reason="e-mail not configured")
        return "skipped"

    label = period or "novo período"
    # No "attachment" key on purpose: Brevo rejects an empty array.
    payload: dict[str, Any] = {
        "sender": {"email": settings.report_email_from, "name": "SUSEP Insights"},
        "to": _recipients(settings.report_email_to),
        "subject": f"SUSEP SES — novo período ingerido ({label})",
        "textContent": (
            f"A ingestão detectou e carregou um novo período da base SUSEP SES: {label}.\n\n"
            "Os marts foram reconstruídos (dbt build) e o relatório de insights será "
            "gerado em seguida."
        ),
    }
    return _deliver(payload, settings)
