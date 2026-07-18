"""Observability: structured JSON events with a trace_id.

Reliability improvement: every skill activation, tool call, error and token
tick is emitted as a structured event, so failures are replayable and
``pulse doctor`` can pinpoint what went wrong.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class Event:
    """A single structured observability event: timestamp, trace_id, kind and payload."""

    ts: float
    trace_id: str
    kind: str
    data: dict[str, Any]

    def to_json(self) -> str:
        """Serialize the event (plus its data payload) to a single JSON line."""
        return json.dumps(
            {"ts": self.ts, "trace_id": self.trace_id, "kind": self.kind, **self.data},
            ensure_ascii=False,
        )


class Observability:
    """Structured JSON event emitter with a per-session ``trace_id`` for replayable traces.

    Events are capped at ``max_events`` (default 5000) to prevent unbounded memory growth
    in long-running services (``pulse serve``).
    """

    def __init__(
        self,
        trace_id: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        max_events: int = 5000,
    ):
        self.trace_id = trace_id or uuid.uuid4().hex[:12]
        self.events: list[Event] = []
        self._log = logger or logging.getLogger("pulse")
        self._max_events = max_events
        self._ext = None

    def emit(self, kind: str, **data: Any) -> None:
        """Append an event of ``kind`` and log it at DEBUG."""
        ev = Event(ts=time.time(), trace_id=self.trace_id, kind=kind, data=data)
        self.events.append(ev)
        if len(self.events) > self._max_events:
            self.events = self.events[-self._max_events :]
        self._log.debug(ev.to_json())
        # Optional trace export for LangSmith/LangFuse
        try:
            ext = getattr(self, "_ext", None)
            if ext is not None:
                ts = getattr(ext, "trace_store", None)
                if ts is not None:
                    from pulse.observability.tracing import Trace

                    ts.record(
                        Trace(
                            trace_id=self.trace_id,
                            span_id=uuid.uuid4().hex[:12],
                            name=kind,
                            kind=kind,
                            data=data,
                        )
                    )
                for tracer in (
                    getattr(ext, "langsmith", None),
                    getattr(ext, "langfuse", None),
                ):
                    if tracer is not None:
                        try:
                            tracer.export(
                                [
                                    Trace(
                                        trace_id=self.trace_id,
                                        span_id=uuid.uuid4().hex[:12],
                                        name=kind,
                                        kind=kind,
                                        data=data,
                                    )
                                ]
                            )
                        except Exception:
                            pass
        except Exception:
            pass

    def token_usage(self, prompt: int, completion: int, total: int) -> None:
        """Emit a ``token_usage`` event with prompt/completion/total counts."""
        self.emit("token_usage", prompt=prompt, completion=completion, total=total)

    def skill_activated(self, name: str) -> None:
        """Emit a ``skill_activated`` event for the named skill."""
        self.emit("skill_activated", skill=name)

    def tool_called(self, name: str, ok: bool, detail: str = "") -> None:
        """Emit a ``tool_called`` event capturing name, success flag and detail string."""
        self.emit("tool_called", tool=name, ok=ok, detail=detail)

    def error(self, error_class: str, message: str) -> None:
        """Emit an ``error`` event with the classified error_class and message."""
        self.emit("error", error_class=error_class, message=message)

    def replay(self) -> list[str]:
        """Return all stored events as a list of JSON strings (for diagnostics/``pulse doctor``)."""
        return [e.to_json() for e in self.events]
