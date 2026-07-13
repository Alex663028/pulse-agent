"""Gateway abstraction — multi-platform entry points.

A Gateway is anything that accepts user input, routes it through the
orchestrator, and delivers the answer back through a channel (CLI, TUI,
Telegram, Discord, ...). Gateways share the same Runtime and can be started
together with ``pulse serve``.

Scheduler is NOT a Gateway — it operates on its own background thread and
runs cron-triggered tasks without waiting for user input.
"""
from __future__ import annotations

import signal
import threading
from abc import ABC, abstractmethod
from typing import Optional

from pulse.cli.runtime import Runtime


class Gateway(ABC):
    name: str = "gateway"

    @abstractmethod
    def start(self, runtime: Runtime) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...


class GatewayManager:
    def __init__(self, gateways: Optional[list[Gateway]] = None):
        self.gateways: list[Gateway] = list(gateways or [])
        self._threads: list[threading.Thread] = []
        self._running = False

    def add(self, gw: Gateway) -> None:
        self.gateways.append(gw)

    def start_all(self, runtime: Runtime) -> None:
        self._running = True
        for gw in self.gateways:
            t = threading.Thread(target=gw.start, args=(runtime,), daemon=True, name=gw.name)
            t.start()
            self._threads.append(t)

    def stop_all(self) -> None:
        self._running = False
        for gw in self.gateways:
            try:
                gw.stop()
            except Exception:
                pass
        for t in self._threads:
            t.join(timeout=2)
        self._threads.clear()

    def wait(self) -> None:
        """Block until interrupted (Ctrl-C)."""
        try:
            signal.pause()
        except (KeyboardInterrupt, AttributeError):
            pass
        self.stop_all()
