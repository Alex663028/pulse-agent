"""M3 tests: subagent parallelism + enhanced scheduler."""
from __future__ import annotations

import time

from pulse.llm.provider import MockProvider
from pulse.orchestrator.subagent import (
    SubagentPool,
    SubagentTask,
    SubagentResult,
    decompose,
    merge_results,
)
from pulse.scheduler.cron import (
    Scheduler,
    _cron_matches,
    parse_natural,
)


# ---- subagent pool ----
def test_pool_runs_in_parallel():
    prov = MockProvider()
    pool = SubagentPool(max_workers=3)
    tasks = [
        SubagentTask(id="a", description="say hello", timeout=5),
        SubagentTask(id="b", description="say world", timeout=5),
    ]
    results = pool.run(tasks, primary=prov)
    assert len(results) == 2
    for r in results:
        assert r.success is True
        assert r.answer  # mock returns an answer


def test_pool_error_isolation():
    """One sub-agent failing must not crash the pool or block others."""

    class FailingMock(MockProvider):
        def chat(self, messages, tools=None, tool_choice=None, **kwargs):
            last = next((m.content for m in reversed(messages) if m.role == "user"), "")
            if "fail" in last.lower():
                raise RuntimeError("simulated sub-agent crash")
            return super().chat(messages, tools=tools, tool_choice=tool_choice, **kwargs)

    prov = FailingMock()
    pool = SubagentPool(max_workers=2)
    tasks = [
        SubagentTask(id="ok", description="say hello"),
        SubagentTask(id="bad", description="fail deliberately", timeout=5),
    ]
    results = pool.run(tasks, primary=prov)
    assert len(results) == 2
    assert any(r.success for r in results)
    assert any(not r.success for r in results)  # the bad one crashed


def test_decompose_heuristic():
    subs = decompose("collect data, analyze trends, and write report")
    assert len(subs) >= 2


def test_decompose_numbered():
    subs = decompose("1. research competitors 2. analyze pricing 3. draft summary")
    assert len(subs) == 3


def test_decompose_single():
    subs = decompose("hello")
    assert len(subs) == 1


def test_merge_results():
    prov = MockProvider()
    results = [
        SubagentResult(task_id="a", success=True, answer="The sky is blue."),
        SubagentResult(task_id="b", success=True, answer="Grass is green."),
    ]
    merged = merge_results("describe nature", results, llm=prov)
    assert "sky" in merged.lower() or "blue" in merged.lower() or "The sky is" in merged
    assert "grass" in merged.lower() or "green" in merged.lower() or "Grass is" in merged


# ---- scheduler enhanced ----
def test_cron_expression_matches():
    from datetime import datetime
    dt = datetime(2026, 1, 1, 8, 0)  # Thu Jan 1 2026, 08:00
    assert _cron_matches("0 8 * * *", dt)
    assert not _cron_matches("0 9 * * *", dt)
    assert _cron_matches("30 8 * * *", datetime(2026, 1, 1, 8, 30))
    assert not _cron_matches("30 8 * * *", dt)


def test_natural_language_parsing():
    sec, cron = parse_natural("hourly")
    assert sec == 3600
    sec2, cron2 = parse_natural("every 5 min")
    assert sec2 == 300


def test_scheduler_pause_resume():
    s = Scheduler()
    results = []

    s.add("counter", 0.1, lambda: results.append(1))
    s.start()
    time.sleep(1.0)
    s.stop()
    initial = len(results)
    assert initial >= 1

    # pause and restart
    results.clear()
    s.pause("counter")
    s.start()
    time.sleep(1.0)
    s.stop()
    assert len(results) == 0  # paused -> no new runs

    s.resume("counter")
    results.clear()
    s.start()
    time.sleep(1.0)
    s.stop()
    assert len(results) >= 1  # resumed -> runs again


def test_scheduler_history():
    s = Scheduler()
    s.add("echo", 0.1, lambda: None)
    s.start()
    time.sleep(1.0)
    s.stop()
    assert len(s.history) >= 1
    for h in s.history:
        assert isinstance(h.success, bool)
