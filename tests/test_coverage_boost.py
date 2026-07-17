"""Tests for previously uncovered modules: compactor, session_index, hub, tools/base, provider, cron edges."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from pulse.config.settings import DEFAULT_BASE_URL, ModelSettings, Settings
from pulse.llm.config import build_router
from pulse.llm.provider import LLMError, LLMMessage, LLMResponse, OpenAICompatProvider, ToolCall, Usage
from pulse.memory.compactor import compact
from pulse.memory.session_index import SessionIndex
from pulse.scheduler.cron import Job, Scheduler, _cron_matches, parse_natural
from pulse.skills.hub import install_skill
from pulse.skills.loader import SkillRecord, dump_skill_md, parse_skill_md
from pulse.storage.engine import Storage
from pulse.tools.base import CalcTool, ListDirTool, ReadFileTool
from tests._helpers import make_runtime


# ---- compactor (was 0%) ----
def test_compactor_naive_short_text():
    assert compact("hello", keep_tokens=100) == "hello"


def test_compactor_naive_long_text():
    long = "x" * 5000
    result = compact(long, keep_tokens=100, llm=None)
    assert len(result) < len(long)
    assert "compressed" in result


def test_compactor_with_llm_success():
    from tests._helpers import StubProvider
    mock = StubProvider()
    mock.add_scripted_response(LLMResponse(content="Summary: key points here.", model="stub"))
    result = compact("long text " * 200, keep_tokens=50, llm=mock)
    assert "Summary" in result


def test_compactor_with_llm_failure_falls_back():
    from tests._helpers import StubProvider
    class FailingStub(StubProvider):
        def chat(self, *a, **kw):
            raise RuntimeError("LLM down")
    result = compact("x" * 5000, keep_tokens=100, llm=FailingStub())
    assert len(result) < 5000  # fell back to naive


# ---- session_index (was 0%) ----
def test_session_index_basic():
    storage = Storage(Path("/tmp") / f"pulse_cov_si_{uuid.uuid4().hex}" / "test.db")
    si = SessionIndex(storage)
    si.index_turn("sess1", "user asked about python")
    hits = storage.search_memory("python")
    assert any("python" in h.get("content", "") for h in hits)


def test_session_index_empty_skipped():
    storage = Storage(Path("/tmp") / f"pulse_cov_si2_{uuid.uuid4().hex}" / "test.db")
    si = SessionIndex(storage)
    si.index_turn("sess1", "")  # empty -> skipped
    si.index_turn("sess1", "   ")  # whitespace -> skipped
    assert len(storage.search_memory("anything")) == 0


# ---- tools/base (was 65%) ----
def test_read_file_tool_success():
    t = ReadFileTool()
    p = Path("/tmp/pulse_cov_rf.txt")
    p.write_text("hello world")
    r = t.run(path=str(p))
    assert r.ok and "hello" in r.output
    os.unlink(p)


def test_read_file_tool_missing():
    t = ReadFileTool()
    r = t.run(path="/nonexistent/file.txt")
    assert not r.ok
    assert "no such file" in r.error


def test_list_dir_tool_success():
    t = ListDirTool()
    d = Path("/tmp/pulse_cov_dir")
    d.mkdir(exist_ok=True)
    (d / "a.txt").write_text("a")
    r = t.run(path=str(d))
    assert r.ok and "a.txt" in r.output


def test_list_dir_tool_error():
    t = ListDirTool()
    r = t.run(path="/nonexistent/dir")
    assert not r.ok


def test_calc_tool_basic():
    t = CalcTool()
    assert t.run(expr="2+3").output == "5"
    assert t.run(expr="10-4").output == "6"
    assert t.run(expr="6*7").output == "42"


def test_calc_tool_division():
    t = CalcTool()
    r = t.run(expr="10/4")
    assert r.ok
    assert float(r.output) == 2.5


def test_calc_tool_unary():
    t = CalcTool()
    assert t.run(expr="-5").output == "-5"


def test_calc_tool_invalid():
    t = CalcTool()
    r = t.run(expr="import os")
    assert not r.ok


def test_tool_to_schema():
    t = CalcTool()
    s = t.to_schema()
    assert s["type"] == "function"
    assert s["function"]["name"] == "calc"
    assert "expr" in s["function"]["parameters"]["properties"]


# ---- provider (was 66%) ----
def test_llm_message_to_openai():
    msg = LLMMessage(role="user", content="hello")
    assert msg.to_openai() == {"role": "user", "content": "hello"}


def test_llm_message_with_tool_calls():
    tc = ToolCall(id="c1", name="calc", arguments={"expr": "1+1"})
    msg = LLMMessage(role="assistant", content="", tool_calls=[tc])
    d = msg.to_openai()
    assert d["tool_calls"][0]["function"]["name"] == "calc"
    assert json.loads(d["tool_calls"][0]["function"]["arguments"]) == {"expr": "1+1"}


def test_llm_message_tool_role():
    msg = LLMMessage(role="tool", content="42", name="calc", tool_call_id="c1")
    d = msg.to_openai()
    assert d["tool_call_id"] == "c1"
    assert d["name"] == "calc"


def test_usage_total():
    u = Usage(prompt_tokens=10, completion_tokens=20)
    assert u.total == 30


def test_stub_provider_scripted():
    from tests._helpers import StubProvider
    r1 = LLMResponse(content="first", model="stub")
    r2 = LLMResponse(content="second", model="stub")
    p = StubProvider()
    p.add_scripted_response(r1)
    p.add_scripted_response(r2)
    assert p.chat([LLMMessage(role="user", content="x")]).content == "first"
    assert p.chat([LLMMessage(role="user", content="x")]).content == "second"


def test_stub_provider_no_tools_no_call_pattern():
    from tests._helpers import StubProvider
    p = StubProvider()
    r = p.chat([LLMMessage(role="user", content="plain text")], tools=None)
    assert r.content.startswith("Acknowledged")


def test_openai_compat_provider_init():
    p = OpenAICompatProvider(base_url="http://localhost:11434/v1", api_key="test", model="qwen2.5:7b")
    assert p.base_url == "http://localhost:11434/v1"
    assert p.model == "qwen2.5:7b"


def test_openai_compat_provider_error_wrapped():
    p = OpenAICompatProvider(base_url="http://localhost:1/v1", api_key="x", model="m", timeout=0.5)
    with pytest.raises(LLMError):
        p.chat([LLMMessage(role="user", content="hi")])


# ---- OpenAI-compatible base_url (any endpoint) ----
def test_make_compat_respects_explicit_base_url():
    """A built-in provider (openai) must use an explicitly-set base_url
    instead of the hardcoded official URL."""
    s = Settings(model=ModelSettings(provider="openai", model="gpt-4o", base_url="https://my-gateway.example.com/v1"))
    router = build_router(s)
    assert router.primary.base_url == "https://my-gateway.example.com/v1"
    assert router.primary.name == "openai-compat"


def test_make_compat_openrouter_respects_explicit_base_url():
    s = Settings(model=ModelSettings(provider="openrouter", model="openai/gpt-4o", base_url="https://proxy.local/v1"))
    router = build_router(s)
    assert router.primary.base_url == "https://proxy.local/v1"


def test_make_compat_falls_back_to_official_when_default():
    """When base_url is still the default (local Ollama addr), built-in
    providers should resolve to their official endpoint."""
    s = Settings(model=ModelSettings(provider="openai", model="gpt-4o"))
    assert s.model.base_url == DEFAULT_BASE_URL
    router = build_router(s)
    assert router.primary.base_url == "https://api.openai.com/v1"


def test_make_compat_unknown_provider_uses_base_url():
    s = Settings(model=ModelSettings(provider="custom", model="m", base_url="https://anything/v1"))
    router = build_router(s)
    assert router.primary.base_url == "https://anything/v1"


def test_make_compat_fallback_chain_preserves_base_url():
    """Fallback providers must also respect explicit base_urls."""
    s = Settings(
        model=ModelSettings(
            provider="openai",
            model="gpt-4o",
            base_url="https://gw.example.com/v1",
            fallback=["openrouter:openai/gpt-4o"],
        )
    )
    router = build_router(s)
    assert router.primary.base_url == "https://gw.example.com/v1"
    assert router.fallbacks[0].base_url == "https://gw.example.com/v1"


# ---- cron edges (was 71%) ----
def test_cron_matches_wildcard():
    from datetime import datetime
    dt = datetime(2026, 6, 15, 14, 30)
    assert _cron_matches("* * * * *", dt)


def test_cron_matches_specific():
    from datetime import datetime
    dt = datetime(2026, 6, 15, 14, 30)
    assert _cron_matches("30 14 15 6 *", dt)
    assert not _cron_matches("31 14 15 6 *", dt)


def test_cron_matches_range():
    from datetime import datetime
    dt = datetime(2026, 6, 15, 10, 0)
    assert _cron_matches("0 9-17 * * *", dt)


def test_cron_invalid_fields():
    from datetime import datetime
    dt = datetime(2026, 6, 15, 10, 0)
    assert not _cron_matches("0 10", dt)  # only 2 fields


def test_parse_natural_every_sec():
    sec, _ = parse_natural("every 30 sec")
    assert sec == 30


def test_parse_natural_every_hour():
    sec, _ = parse_natural("every 2 hours")
    assert sec == 7200


def test_parse_natural_default():
    sec, _ = parse_natural("something unknown")
    assert sec == 3600


def test_job_post_init_sets_created_at():
    j = Job(name="test", interval=60, fn=lambda: None)
    assert j.created_at != ""


def test_scheduler_remove_nonexistent():
    s = Scheduler()
    s.remove("no-such-job")  # should not raise


def test_scheduler_pause_nonexistent():
    s = Scheduler()
    assert s.pause("no-such") is False


def test_scheduler_resume_nonexistent():
    s = Scheduler()
    assert s.resume("no-such") is False


# ---- hub (was 26%) ----
def test_hub_install_from_local_dir():
    rt = make_runtime(Path("/tmp") / f"pulse_cov_hub_{uuid.uuid4().hex}")
    # create a temp skill dir
    skill_dir = rt.settings.data_dir / "temp-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    fm = {"name": "temp-skill", "description": "temp", "version": "1.0.0"}
    body = "# Temp\nsteps"
    (skill_dir / "SKILL.md").write_text(
        "---\n" + __import__("yaml").safe_dump(fm, sort_keys=False) + "---\n\n" + body, encoding="utf-8"
    )
    name = install_skill(rt.registry, str(skill_dir), rt.settings)
    assert name == "temp-skill"
    assert rt.registry.get("temp-skill") is not None


def test_hub_install_invalid_location():
    rt = make_runtime(Path("/tmp") / f"pulse_cov_hub2_{uuid.uuid4().hex}")
    with pytest.raises(ValueError):
        install_skill(rt.registry, "not-a-path-or-url", rt.settings)


# ---- loader edge cases ----
def test_parse_skill_md_no_frontmatter():
    fm, body = parse_skill_md("just plain text")
    assert fm == {}
    assert "just plain text" in body


def test_dump_skill_md_roundtrip():
    rec = SkillRecord(
        id="test@1.0.0", name="test", path=Path("/tmp/x"), version="1.0.0",
        frontmatter={"name": "test", "description": "a test", "version": "1.0.0"},
        body="# Test\n\ndo stuff",
        status="candidate",
    )
    text = dump_skill_md(rec)
    assert "---" in text
    assert "test" in text
    fm, body = parse_skill_md(text)
    assert fm["name"] == "test"
    assert "do stuff" in body


# ---- storage edge cases ----
def test_storage_query_trajectories_filters():
    s = Storage(Path("/tmp") / f"pulse_cov_st_{uuid.uuid4().hex}" / "t.db")
    s.log_trajectory("t1", "s1", True, ["alpha"], {"task": "a", "answer": "x"})
    s.log_trajectory("t2", "s2", False, ["beta"], {"task": "b", "answer": "y"})
    assert len(s.query_trajectories(outcome=True)) == 1
    assert len(s.query_trajectories(outcome=False)) == 1
    assert len(s.query_trajectories(skill="alpha")) == 1
    assert len(s.query_trajectories(skill="gamma")) == 0


def test_storage_search_memory_no_fts5_fallback():
    """If FTS5 unavailable, search degrades to substring. Test with a known term."""
    s = Storage(Path("/tmp") / f"pulse_cov_st2_{uuid.uuid4().hex}" / "t.db")
    s.index_memory("s1", "the quick brown fox jumps")
    hits = s.search_memory("quick")
    assert len(hits) >= 1
