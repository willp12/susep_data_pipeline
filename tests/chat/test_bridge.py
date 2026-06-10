from collections.abc import AsyncIterator
from typing import Any

import pytest

from src.chat.bridge import ChatBridge
from src.chat.session import ChatEvent
from tests.agent._fakes import FakeStore


class FakeSession:
    """Quacks like ChatSession without SDK or network."""

    def __init__(self) -> None:
        self.provider = "local"
        self.model = "fake-model"
        self.total_cost_usd = 0.0
        self.entered = False
        self.exited = False
        self.fail_with: Exception | None = None

    async def __aenter__(self) -> "FakeSession":
        self.entered = True
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.exited = True

    async def ask(self, prompt: str) -> AsyncIterator[ChatEvent]:
        if self.fail_with:
            raise self.fail_with
        yield ChatEvent(kind="tool", text="read_report: 2026-05-23")
        yield ChatEvent(kind="text", text=f"resposta para: {prompt}")
        yield ChatEvent(kind="result", data={"cost_usd": None})


def _seeded_store() -> FakeStore:
    store = FakeStore()
    store.save_manifest(
        {
            "reports": [
                {"stem": "2026-05-22", "titles": ["1. A"]},
                {"stem": "2026-05-23", "titles": ["1. B"]},
            ]
        }
    )
    return store


def _bridge(session: FakeSession) -> ChatBridge:
    return ChatBridge(store=_seeded_store(), session_factory=lambda store: session)  # type: ignore[arg-type,return-value]


def test_start_connects_and_loads_manifest_desc() -> None:
    session = FakeSession()
    bridge = _bridge(session)
    bridge.start()
    assert session.entered
    assert [e["stem"] for e in bridge.manifest_entries] == ["2026-05-23", "2026-05-22"]
    assert bridge.provider == "local"
    assert bridge.model == "fake-model"
    bridge.close()
    assert session.exited


def test_ask_streams_events_in_order() -> None:
    bridge = _bridge(FakeSession())
    bridge.start()
    events = list(bridge.ask("qual o LR?"))
    assert [e.kind for e in events] == ["tool", "text", "result"]
    assert events[1].text == "resposta para: qual o LR?"
    bridge.close()


def test_ask_propagates_session_errors() -> None:
    session = FakeSession()
    session.fail_with = RuntimeError("boom")
    bridge = _bridge(session)
    bridge.start()
    with pytest.raises(RuntimeError, match="boom"):
        list(bridge.ask("x"))
    bridge.close()


def test_ask_before_start_raises() -> None:
    bridge = _bridge(FakeSession())
    with pytest.raises(RuntimeError, match="not started"):
        list(bridge.ask("x"))


def test_restart_creates_fresh_session() -> None:
    sessions = [FakeSession(), FakeSession()]
    store = _seeded_store()
    bridge = ChatBridge(store=store, session_factory=lambda s: sessions.pop(0))  # type: ignore[arg-type,return-value]
    bridge.start()
    first = bridge._session
    bridge.restart()
    assert bridge._session is not first
    assert bridge._session is not None
    bridge.close()
