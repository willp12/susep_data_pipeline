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
    out = news_search.search_news(
        "CAIXA parceria", days_back=30, max_results=3, api_key="tvly-test"
    )

    assert captured["url"] == "https://api.tavily.com/search"
    assert captured["json"] == {
        "query": "CAIXA parceria",
        "topic": "news",
        "days": 30,
        "max_results": 3,
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
    news_search.search_news("x", max_results=99, api_key="k")
    assert captured["json"]["max_results"] == news_search.MAX_RESULTS_CAP


def test_search_news_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        news_search,
        "get_settings",
        lambda: type("S", (), {"tavily_api_key": ""})(),
    )
    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        news_search.search_news("x")
