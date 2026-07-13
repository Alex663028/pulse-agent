"""M2 tests: gateways + scheduler."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from pulse.gateways.base import Gateway, GatewayManager
from pulse.gateways.telegram import TelegramGateway
from pulse.gateways.tui import TuiGateway
from pulse.scheduler.cron import Scheduler
from tests._helpers import make_runtime


# ---- GatewayManager ----
def test_manager_start_stop():
    started = []

    class Mock(Gateway):
        name = "mock"

        def __init__(self, label):
            self.label = label

        def start(self, runtime):
            started.append(self.label)
            time.sleep(0.05)

        def stop(self):
            started.remove(self.label)

    mgr = GatewayManager([Mock("a"), Mock("b")])
    mgr.start_all(None)
    time.sleep(0.15)
    assert sorted(started) == ["a", "b"]
    mgr.stop_all()
    time.sleep(0.15)
    assert started == []


# ---- TUI slash commands ----
def test_tui_slash_commands():
    rt = make_runtime(Path("/tmp/pulse_m2_tui"))

    class FakeConsole:
        def __init__(self):
            self.out: list[str] = []

        def print(self, *a, **kw):
            self.out.append(" ".join(str(x) for x in a))

        def input(self, prompt=""):
            return ""

    tui = TuiGateway()
    fc = FakeConsole()
    tui._console = fc
    tui._active = False  # prevent loop

    tui._handle_slash("/help", rt, fc)
    assert any("help" in line.lower() or "skills" in line.lower() for line in fc.out)

    tui._handle_slash("/skills", rt, fc)
    tui._handle_slash("/model", rt, fc)
    tui._handle_slash("/quit", rt, fc)
    assert not tui._active


# ---- Telegram chunks ----
def test_telegram_chunks():
    tg = TelegramGateway("fake")
    assert tg._chunks("hi", 4000) == ["hi"]
    long = "a" * 5000
    chunks = tg._chunks(long, 200)
    assert all(len(c) <= 200 for c in chunks)
    assert "".join(chunks).replace("\n\n", "") == long


# ---- Scheduler ----
def test_scheduler_runs_job():
    s = Scheduler()
    results = []

    s.add("tick", 0.1, lambda: results.append(1))
    assert len(s.list()) == 1
    s.start()
    time.sleep(1.0)
    s.stop()
    assert len(results) >= 1  # at least one tick in 1s

    s.remove("tick")
    assert len(s.list()) == 0
