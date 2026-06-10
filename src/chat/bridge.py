"""Sync bridge between a UI and the async ChatSession.

Streamlit re-runs the whole script on every interaction and its callbacks are
synchronous, while ``ChatSession`` is async and must stay alive across reruns
(the conversation context lives in the SDK client). The bridge owns the
session on a dedicated event-loop thread and exposes blocking calls:

    bridge = ChatBridge()
    bridge.start()
    for event in bridge.ask("pergunta"):   # sync iterator of ChatEvents
        ...

The UI keeps the bridge in ``st.session_state``, so each browser session gets
its own conversation. No streamlit import here — the bridge is UI-agnostic
and unit-testable with a fake session factory.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import Callable, Iterator
from typing import Any

from src.agent.publisher import ReportStore
from src.chat.session import ChatEvent, ChatSession

_START_TIMEOUT_S = 120

# Sentinel closing the event queue (None can't be used: it's falsy and dull).
_DONE = object()


def _default_session_factory(store: ReportStore) -> ChatSession:
    return ChatSession(store=store)


class ChatBridge:
    """Owns a ChatSession on a dedicated event-loop thread."""

    def __init__(
        self,
        *,
        store: ReportStore | None = None,
        session_factory: Callable[[ReportStore], ChatSession] | None = None,
    ) -> None:
        self._store = store or ReportStore()
        self._session_factory = session_factory or _default_session_factory
        self._session: ChatSession | None = None
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="chat-bridge", daemon=True
        )
        self._thread.start()
        self.manifest_entries: list[dict[str, Any]] = []

    def _run(self, coro: Any, timeout: float | None = None) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Create and connect the session; load the manifest for the sidebar."""
        if self._session is not None:
            return
        entries = self._store.load_manifest().get("reports", [])
        self.manifest_entries = sorted(entries, key=lambda e: str(e["stem"]), reverse=True)
        session = self._session_factory(self._store)
        self._run(session.__aenter__(), timeout=_START_TIMEOUT_S)
        self._session = session

    def restart(self) -> None:
        """Drop the conversation and start a fresh session."""
        self.close()
        self.start()

    def close(self) -> None:
        if self._session is not None:
            self._run(self._session.__aexit__(None, None, None), timeout=_START_TIMEOUT_S)
            self._session = None

    # -- conversation --------------------------------------------------------

    @property
    def provider(self) -> str:
        return self._session.provider if self._session else "?"

    @property
    def model(self) -> str:
        return self._session.model if self._session else "?"

    @property
    def total_cost_usd(self) -> float:
        return self._session.total_cost_usd if self._session else 0.0

    def ask(self, prompt: str) -> Iterator[ChatEvent]:
        """Blocking iterator over the answer's events (text/tool/result)."""
        if self._session is None:
            raise RuntimeError("ChatBridge not started — call start() first.")
        session = self._session
        events: queue.Queue[Any] = queue.Queue()

        async def _pump() -> None:
            try:
                async for event in session.ask(prompt):
                    events.put(event)
            except Exception as exc:  # surfaced on the consumer side
                events.put(exc)
            finally:
                events.put(_DONE)

        asyncio.run_coroutine_threadsafe(_pump(), self._loop)
        while True:
            item = events.get()
            if item is _DONE:
                return
            if isinstance(item, Exception):
                raise item
            yield item
