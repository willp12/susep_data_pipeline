"""search_news — web/news search via the Tavily API.

Gives the agent market context the SES data can't show (partnerships, M&A,
regulatory moves, distribution deals). It complements — never replaces — the
BigQuery numbers: prompt rules require news to be cited with source + date +
URL and clearly labelled as external context.

The function is a thin, defensive HTTP client; the per-run search cap and the
search log (for the future "Fontes web" appendix) live in the sdk_tools
wrapper, mirroring how run_sql's guardrails are layered.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from src.config import get_settings

log = structlog.get_logger(__name__)

_TAVILY_URL = "https://api.tavily.com/search"
_TIMEOUT_S = 20.0

MAX_RESULTS_CAP = 10

# Social networks pollute general-topic results and never carry the kind of
# market news the agent needs.
_EXCLUDED_DOMAINS = [
    "instagram.com",
    "facebook.com",
    "youtube.com",
    "x.com",
    "twitter.com",
    "linkedin.com",
    "tiktok.com",
]


def _time_range(days_back: int) -> str:
    """Map a day window to Tavily's general-topic time_range buckets."""
    if days_back <= 1:
        return "day"
    if days_back <= 7:
        return "week"
    if days_back <= 31:
        return "month"
    return "year"


def search_news(
    query: str,
    *,
    days_back: int = 90,
    max_results: int = 5,
    api_key: str | None = None,
    include_domains: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Search recent Brazil-focused news; returns [{title, source, url, published, snippet}].

    Uses ``topic=general`` + ``country=brazil`` instead of Tavily's news
    vertical: the news topic skews to global/English mainstream outlets and
    ignores the country boost, which made it miss the Brazilian (and the
    specialised insurance) press almost entirely. Recency comes from
    ``time_range`` (bucketed from ``days_back``); ``max_results`` is capped at
    MAX_RESULTS_CAP. ``include_domains`` (or NEWS_INCLUDE_DOMAINS in .env)
    optionally restricts to a whitelist of outlets. Raises RuntimeError on
    missing key or API failure — the sdk_tools wrapper turns that into a tool
    error for the model.
    """
    settings = get_settings()
    key = api_key or settings.tavily_api_key
    if not key:
        raise RuntimeError("TAVILY_API_KEY not set — news search is disabled.")

    payload: dict[str, Any] = {
        "query": query,
        "topic": "general",
        "country": "brazil",
        "time_range": _time_range(int(days_back)),
        "max_results": max(1, min(int(max_results), MAX_RESULTS_CAP)),
    }
    payload["exclude_domains"] = _EXCLUDED_DOMAINS
    domains = include_domains or [
        d.strip() for d in settings.news_include_domains.split(",") if d.strip()
    ]
    if domains:
        payload["include_domains"] = domains
    response = httpx.post(
        _TAVILY_URL,
        json=payload,
        headers={"Authorization": f"Bearer {key}"},
        timeout=_TIMEOUT_S,
    )
    response.raise_for_status()
    data = response.json()

    results = []
    for item in data.get("results", []):
        url = str(item.get("url") or "")
        results.append(
            {
                "title": item.get("title") or "(sem título)",
                "source": url.split("/")[2] if "://" in url else "",
                "url": url,
                "published": item.get("published_date") or None,
                "snippet": (item.get("content") or "").strip()[:500],
            }
        )
    log.info("agent.tool.search_news.ok", query=query, results=len(results))
    return results
