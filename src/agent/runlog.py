"""Buffer the run's structlog events so they can be published as JSONL.

The collector is a structlog processor: registered in the processor chain
(after ``add_log_level``/``TimeStamper``, so their fields are present), it
keeps a JSON line per event and passes the event through untouched. At the
end of the run the publisher uploads the buffer to ``logs/<year>/<stem>.jsonl``.

Module-level singleton: the agent process drives exactly one run.
"""

from __future__ import annotations

import json
from collections.abc import MutableMapping
from typing import Any


class RunLogCollector:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(
        self,
        logger: Any,
        method_name: str,
        event_dict: MutableMapping[str, Any],
    ) -> MutableMapping[str, Any]:
        self.lines.append(json.dumps(dict(event_dict), default=str, ensure_ascii=False))
        return event_dict


collector = RunLogCollector()


def get_run_log_lines() -> list[str]:
    return list(collector.lines)
