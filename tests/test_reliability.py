"""Tests for the reliability layer: error classification, recovery, budget, and
fault-tolerant orchestration."""
from __future__ import annotations

from pathlib import Path

import pytest

from pulse.config.settings import ModelSettings, Settings
from pulse.llm.config import build_router
from pulse.llm.provider import LLMError, LLMMessage, MockProvider
from pulse.llm.router import Router
from pulse.memory.store import MemoryStore
from pulse.orchestrator.context_budget import ContextBudget
from pulse.orchestrator.loop import Orchestrator
from pulse.orchestrator.recovery import (
    CtxOverflowError,
    ErrorClass,
    classify,
    guarded,
)
from pulse.orchestrator.recovery import RecoveryError
from pulse.skills.registry import SkillRegistry
from pulse.storage.engine import Storage
from pulse.tools.builtin import register_builtin_tools
from pulse.tools.registry import ToolRegistry
from tests._helpers import flaky_provider, make_runtime


# ---- error classification ----
def test_classify():
    assert classify(LLMError("503 unavailable")) == ErrorClass.TRANSIENT
    assert classify(LLMError("rate limit 429")) == ErrorClass.TRANSIENT
    assert classify(LLMError("I cannot fulfill this request")) == ErrorClass.LLM_REFUSE
    assert classify(ValueError("bad arg")) == ErrorClass.TOOL_FAIL
    assert classify(RuntimeError("boom")) == ErrorClass.TOOL_FAIL
    assert classify(Exception("weird")) == ErrorClass.UNKNOWN


def test_guarded_retries_transient():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise LLMError("503 transient")
        return "ok"

    assert guarded(flaky, allow=(ErrorClass.TRANSIENT,)) == "ok"
    assert calls["n"] == 3


def test_guarded_fails_fast_on_tool_error():
    def bad():
        raise ValueError("tool broke")

    with pytest.raises(RecoveryError):
        guarded(bad, allow=(ErrorClass.TRANSIENT,))


# ---- context budget ----
def test_context_budget_overflow():
    # hard cap: reserving past the max raises
    b = ContextBudget(max_tokens=10, soft_ratio=0.5)
    with pytest.raises(CtxOverflowError):
        b.reserve(50)

    # soft threshold: reserving past soft (but under hard) flags compaction
    b2 = ContextBudget(max_tokens=100, soft_ratio=0.5)
    b2.reserve(60)
    assert b2.over_soft is True
    assert b2.used == 60


# ---- orchestrator fault tolerance ----
def _manual_runtime(tmp_path: Path, router: Router):
    settings = Settings(config_dir=tmp_path, data_dir=tmp_path / "data")
    settings.model = ModelSettings(provider="mock", model="mock-1")
    storage = Storage(settings.db_path)
    memory = MemoryStore(settings, storage)
    registry = SkillRegistry(settings, storage)
    tools = ToolRegistry()
    register_builtin_tools(tools)
    orch = Orchestrator(router, memory, registry, tools, storage, settings)
    return orch


def test_orchestrator_recovers_from_transient():
    orch = _manual_runtime(Path("/tmp/pulse_test_recover"), Router(primary=flaky_provider(failures=2)))
    res = orch.run("say hello")
    assert res.success is True


def test_orchestrator_tool_loop_and_evolution():
    rt = make_runtime(Path("/tmp/pulse_test_toolloop"))
    res = rt.orchestrator.run("compute this [call:calc] 2+3")
    assert res.success is True
    assert any(t["action"].startswith("tool:calc") for t in res.trajectory)
    # auto-evolution should have proposed a candidate skill after a tool-using success
    assert res.candidate_skill is not None


def test_mock_provider_no_tool_loop():
    p = MockProvider()
    r1 = p.chat([LLMMessage(role="user", content="do [call:calc] 1+1")], tools=[{"type": "function"}])
    assert r1.tool_calls and r1.tool_calls[0].name == "calc"
    r2 = p.chat([LLMMessage(role="user", content="do [call:calc] 1+1")], tools=[{"type": "function"}])
    assert not r2.tool_calls  # same tool not re-emitted -> no loop
