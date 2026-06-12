from typing import Any

import httpx
import pytest

import src.agent.tools.news_search as news_search


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)  # type: ignore[arg-type]

    def json(self) -> dict[str, Any]:
        return self._payload


def _stub_settings(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    fields = {"tavily_api_key": "k", "news_include_domains": ""}
    fields.update(overrides)
    monkeypatch.setattr(news_search, "get_settings", lambda: type("S", (), fields)())


def test_search_news_maps_results(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        captured["url"] = url
        captured["json"] = kwargs["json"]
        captured["auth"] = kwargs["headers"]["Authorization"]
        return FakeResponse(
            {
                "results": [
                    {
                        "title": "CAIXA fecha parceria com varejista",
                        "url": "https://valor.globo.com/financas/noticia/x",
                        "published_date": "2026-05-30",
                        "content": "  A CAIXA Seguridade anunciou...  ",
                    },
                    {"url": "https://exame.com/y", "content": ""},
                ]
            }
        )

    monkeypatch.setattr(news_search.httpx, "post", fake_post)
    _stub_settings(monkeypatch)
    out = news_search.search_news(
        "CAIXA parceria", days_back=30, max_results=3, api_key="tvly-test"
    )

    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["json"] == {
        "query": "CAIXA parceria",
        "topic": "general",
        "country": "brazil",
        "time_range": "month",
        "max_results": 3,
        "exclude_domains": news_search._EXCLUDED_DOMAINS,
    }
    assert captured["auth"] == "Bearer tvly-test"

    assert out[0]["title"] == "CAIXA fecha parceria com varejista"
    assert out[0]["source"] == "valor.globo.com"
    assert out[0]["published"] == "2026-05-30"
    assert out[0]["snippet"] == "A CAIXA Seguridade anunciou..."
    # Defensive mapping for sparse results.
    assert out[1]["title"] == "(sem título)"
    assert out[1]["published"] is None


def test_search_news_caps_max_results(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        captured["json"] = kwargs["json"]
        return FakeResponse({"results": []})

    monkeypatch.setattr(news_search.httpx, "post", fake_post)
    _stub_settings(monkeypatch)
    news_search.search_news("x", max_results=99, api_key="k")
    assert captured["json"]["max_results"] == news_search.MAX_RESULTS_CAP


def test_search_news_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_settings(monkeypatch, tavily_api_key="")
    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        news_search.search_news("x")


@pytest.mark.parametrize(
    ("days_back", "expected"),
    [(1, "day"), (7, "week"), (30, "month"), (90, "year"), (400, "year")],
)
def test_time_range_buckets(days_back: int, expected: str) -> None:
    assert news_search._time_range(days_back) == expected


def test_include_domains_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        captured["json"] = kwargs["json"]
        return FakeResponse({"results": []})

    monkeypatch.setattr(news_search.httpx, "post", fake_post)
    _stub_settings(monkeypatch, news_include_domains="sonhoseguro.com.br, cqcs.com.br,")
    news_search.search_news("x")
    assert captured["json"]["include_domains"] == ["sonhoseguro.com.br", "cqcs.com.br"]


def test_explicit_include_domains_beats_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        captured["json"] = kwargs["json"]
        return FakeResponse({"results": []})

    monkeypatch.setattr(news_search.httpx, "post", fake_post)
    _stub_settings(monkeypatch, news_include_domains="cqcs.com.br")
    news_search.search_news("x", api_key="k", include_domains=["valor.globo.com"])
    assert captured["json"]["include_domains"] == ["valor.globo.com"]
