"""LangSmith/LangFuse observability integration.

Trace viewer, debugging, and export for LLM calls, tool executions, and agent runs.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class Trace:
    """A single trace span/event."""

    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    name: str = ""
    kind: str = "span"  # span / event / llm / tool
    data: dict[str, Any] = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0


class TraceStore:
    """In-memory ring buffer for traces, with optional export."""

    def __init__(self, max_traces: int = 1000) -> None:
        self._traces: list[Trace] = []
        self._lock = threading.Lock()
        self._max = max_traces

    def record(self, trace: Trace) -> None:
        with self._lock:
            self._traces.append(trace)
            if len(self._traces) > self._max:
                self._traces = self._traces[-self._max :]

    def get_trace(self, trace_id: str) -> list[Trace]:
        with self._lock:
            return [t for t in self._traces if t.trace_id == trace_id]

    def export_json(self) -> str:
        with self._lock:
            return json.dumps(
                [
                    {
                        "trace_id": t.trace_id,
                        "span_id": t.span_id,
                        "parent_span_id": t.parent_span_id,
                        "name": t.name,
                        "kind": t.kind,
                        "data": t.data,
                        "start_time": t.start_time,
                        "end_time": t.end_time,
                    }
                    for t in self._traces
                ],
                ensure_ascii=False,
            )


class LangSmithTracer:
    """LangSmith-compatible trace exporter."""

    def __init__(self, api_key: str = "", endpoint: str = "https://api.smith.langchain.com") -> None:
        self.api_key = api_key
        self.endpoint = endpoint.rstrip("/")
        self._enabled = bool(api_key)

    def export(self, traces: list[Trace]) -> None:
        if not self._enabled:
            return
        try:
            import urllib.request

            payload = json.dumps(
                [{"name": t.name, "run_type": t.kind, "inputs": t.data} for t in traces]
            ).encode()
            req = urllib.request.Request(
                f"{self.endpoint}/runs",
                data=payload,
                headers={"Content-Type": "application/json", "x-api-key": self.api_key},
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            logger.warning("langsmith export failed: %s", e)


class LangFuseTracer:
    """LangFuse-compatible trace exporter."""

    def __init__(self, public_key: str = "", secret_key: str = "", host: str = "https://cloud.langfuse.com") -> None:
        self.public_key = public_key
        self.secret_key = secret_key
        self.host = host.rstrip("/")
        self._enabled = bool(public_key and secret_key)

    def export(self, traces: list[Trace]) -> None:
        if not self._enabled:
            return
        try:
            import urllib.request
            import urllib.parse

            auth = urllib.parse.quote(self.public_key + ":" + self.secret_key)
            payload = json.dumps(
                [
                    {
                        "id": t.span_id,
                        "trace_id": t.trace_id,
                        "name": t.name,
                        "metadata": t.data,
                    }
                    for t in traces
                ]
            ).encode()
            req = urllib.request.Request(
                f"{self.host}/api/public/ingestion",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Basic {auth}",
                },
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            logger.warning("langfuse export failed: %s", e)
