"""Scrape the SUSEP SES landing page and return the current Base de Dados URL.

SUSEP publishes a single full-base ZIP (``BaseCompleta.zip``) that is
overwritten on each refresh. The landing page exposes it as an anchor inside
``<div id="GEEST">`` pointing at ``redarq.asp?arq=BaseCompleta%2ezip`` (the
``.zip`` extension is URL-encoded as ``%2ezip``), and a nearby
``<span id="ctl00_ContentPlaceHolder1_lblMesAnoCarga">`` carries the reference
period as ``YYYYMM``.

Our job here is narrow: hit the page, pull the canonical download URL, and
surface the period so callers/log consumers can tell which refresh they're
ingesting. We deliberately do NOT guess the parsing — if SUSEP changes the
layout, we dump the raw HTML snippet and fail loud.
"""

from __future__ import annotations

import ssl
import sys
import time
from dataclasses import dataclass
from urllib.parse import unquote, urljoin

import httpx
import structlog
import truststore
from selectolax.parser import HTMLParser

from src.config import get_settings

# SUSEP (and other .gov.br domains) serve an ICP-Brasil certificate chain that
# the certifi bundle does not include. We use truststore's SSLContext which
# defers to the OS trust store (Windows/macOS already trust ICP-Brasil; Linux
# uses the system CA bundle).
#
# We pass this context only to httpx calls that hit SUSEP — doing a global
# ``truststore.inject_into_ssl()`` breaks boto3 S3 multipart uploads with
# "maximum recursion depth exceeded" because urllib3's SSL-wrapping path
# recurses through the patched default SSLContext.
SUSEP_SSL_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

log = structlog.get_logger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}
_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

# Span whose text is the YYYYMM reference period of the current dump.
_PERIOD_SPAN_ID = "ctl00_ContentPlaceHolder1_lblMesAnoCarga"
# Span whose text is the generation timestamp (DD/MM/YYYY HH:MM:SS).
_GENERATED_SPAN_ID = "ctl00_ContentPlaceHolder1_lblDataCarga"


@dataclass(frozen=True)
class LatestZipInfo:
    """Everything we pulled from the landing page about the current dump."""

    url: str
    filename: str
    period: str  # "YYYYMM" if present, else "unknown"
    generated_at: str  # raw SUSEP string ("DD/MM/YYYY HH:MM:SS"), else "unknown"


def fetch_page(url: str, *, max_attempts: int = 3) -> str:
    """GET ``url`` with basic exponential backoff. Raises on final failure."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = httpx.get(
                url,
                headers=_HEADERS,
                timeout=_TIMEOUT,
                follow_redirects=True,
                verify=SUSEP_SSL_CONTEXT,
            )
            resp.raise_for_status()
            return str(resp.text)
        except (httpx.HTTPError, httpx.TransportError) as exc:
            last_exc = exc
            if attempt < max_attempts:
                backoff = 2 ** (attempt - 1)
                log.warning(
                    "scraper.fetch.retry",
                    url=url,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    backoff_s=backoff,
                    error=str(exc),
                )
                time.sleep(backoff)
    raise RuntimeError(f"Failed to fetch {url} after {max_attempts} attempts: {last_exc}")


def _span_text(tree: HTMLParser, span_id: str) -> str:
    node = tree.css_first(f"span#{span_id}")
    if node is None:
        return "unknown"
    return node.text(strip=True) or "unknown"


def _find_base_zip_anchor(tree: HTMLParser) -> str | None:
    """Return the href of the 'Base de Dados do SES' anchor, or None."""
    # Primary: the anchor lives inside <div id="GEEST">. Its href points at
    # redarq.asp with an arq=...%2ezip query param.
    for anchor in tree.css("div#GEEST a[href]"):
        href = (anchor.attributes.get("href") or "").strip()
        if not href:
            continue
        decoded = unquote(href).lower()
        if ".zip" in decoded:
            return href

    # Fallback: scan every anchor, look for redarq.asp? with a zip arg.
    for anchor in tree.css("a[href]"):
        href = (anchor.attributes.get("href") or "").strip()
        if not href:
            continue
        decoded = unquote(href).lower()
        if "redarq.asp" in decoded and ".zip" in decoded:
            return href

    return None


def get_latest_zip_info() -> LatestZipInfo:
    """Return URL + metadata for the current SUSEP SES full-base ZIP."""
    settings = get_settings()
    url = settings.susep_ses_url
    log.info("scraper.fetch.start", url=url)
    html = fetch_page(url)
    tree = HTMLParser(html)

    href = _find_base_zip_anchor(tree)
    if href is None:
        snippet = html[:2000]
        sys.stderr.write(
            "[scraper] Could not find the Base de Dados anchor on SUSEP SES page. "
            "Raw HTML snippet (first 2000 chars):\n"
        )
        sys.stderr.write(snippet)
        sys.stderr.write("\n")
        raise RuntimeError(
            "Could not locate the Base de Dados download link on the SUSEP SES page "
            "(see raw HTML above)."
        )

    absolute_url = urljoin(url, href)
    # Filename is the `arq=` query parameter, URL-decoded, stripped of path.
    filename = unquote(absolute_url.rsplit("arq=", 1)[-1]).split("/")[-1] or "BaseCompleta.zip"
    period = _span_text(tree, _PERIOD_SPAN_ID)
    generated_at = _span_text(tree, _GENERATED_SPAN_ID)

    info = LatestZipInfo(
        url=absolute_url,
        filename=filename,
        period=period,
        generated_at=generated_at,
    )
    log.info(
        "scraper.fetch.ok",
        url=info.url,
        filename=info.filename,
        period=info.period,
        generated_at=info.generated_at,
    )
    return info


def get_latest_zip_url() -> str:
    """Thin convenience wrapper returning just the URL."""
    return get_latest_zip_info().url


def main() -> int:
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ]
    )
    try:
        info = get_latest_zip_info()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"url:          {info.url}")
    print(f"filename:     {info.filename}")
    print(f"period:       {info.period}")
    print(f"generated_at: {info.generated_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
