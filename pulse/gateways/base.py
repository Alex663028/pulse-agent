"""Gateway abstraction — multi-platform entry points.

A Gateway is anything that accepts user input, routes it through the
orchestrator, and delivers the answer back through a channel (CLI, TUI,
Telegram, Discord, ...). Gateways share the same Runtime and can be started
together with ``pulse serve``.

Scheduler is NOT a Gateway — it operates on its own background thread and
runs cron-triggered tasks without waiting for user input.
"""
from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from typing import Optional

from pulse.cli.runtime import Runtime

logger = logging.getLogger(__name__)


class Gateway(ABC):
    """Abstract multi-platform entry point: accepts input via a channel and routes it through the orchestrator."""

    name: str = "gateway"

    @abstractmethod
    def start(self, runtime: Runtime) -> None:
        """Begin serving the gateway against the given runtime (blocks until ``stop``)."""

    @abstractmethod
    def stop(self) -> None:
        """Signal the gateway to stop its serving loop."""


class GatewayManager:
    """Runs a set of gateways concurrently on daemon threads and shuts them down together."""

    def __init__(self, gateways: Optional[list[Gateway]] = None):
        self.gateways: list[Gateway] = list(gateways or [])
        self._threads: list[threading.Thread] = []
        self._running = False
        self._stop_event = threading.Event()

    def add(self, gw: Gateway) -> None:
        """Append a gateway to the managed set."""
        self.gateways.append(gw)

    def start_all(self, runtime: Runtime) -> None:
        """Start every managed gateway on its own daemon thread."""
        self._running = True
        self._stop_event.clear()
        for gw in self.gateways:
            t = threading.Thread(target=gw.start, args=(runtime,), daemon=True, name=gw.name)
            t.start()
            self._threads.append(t)

    def stop_all(self) -> None:
        """Stop every gateway and join its thread (best-effort, 2s timeout each)."""
        self._running = False
        self._stop_event.set()
        for gw in self.gateways:
            try:
                gw.stop()
            except Exception:
                logger.exception("gateway %s stop failed", gw.name)
        for t in self._threads:
            t.join(timeout=5)
        self._threads.clear()

    def wait(self) -> None:
        """Block until interrupted (Ctrl-C)."""
        try:
            self._stop_event.wait()
        except (KeyboardInterrupt, AttributeError):
            pass
        self.stop_all()
