"""Coverage-improving tests for low-coverage pulse modules."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from pulse.skills.evaluator import RunOutcome, SkillEvaluator
from pulse.skills.executable import (
    BaseExecutableSkill,
    SkillHandle,
    load_executable_skills,
    run_skill_tests,
)
from pulse.skills.evolution import _slug, propose_skill
from pulse.skills.hub import _find_skill_dir, install_skill
from pulse.skills.trigger import keyword_select, select
from pulse.skills.loader import SkillRecord, load_skill_dir
from pulse.tools.core import (
    EditFileTool,
    HttpClientTool,
    PythonExecTool,
    ShellExecTool,
    WebFetchTool,
    WebSearchTool,
    WriteFileTool,
)
from pulse.tools.loader import (
    ToolSpec,
    _load_json_spec,
    _load_py_spec,
    _load_yaml_spec,
    load_custom_tools,
    list_custom_tool_specs,
)
from pulse.scheduler.cron import Scheduler, parse_natural, _cron_matches, _parse_cron
from pulse.web.server import PulseWebUI
from tests._helpers import make_runtime


# ========================== skills/evolution.py ==========================


class TestEvolution:
    def test_slug_basic(self):
        assert _slug("write a python script") == "write-python-script"

    def test_slug_invalid_fallback(self):
        assert _slug("!!!") == "task-skill"

    def test_propose_skill_without_llm(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        rec = propose_skill("do stuff", ["step1", "step2"], skills_dir)
        assert (skills_dir / rec.name / "SKILL.md").exists()
        assert rec.status == "candidate"

    def test_propose_skill_llm_refine(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        fake = MagicMock()
        fake.chat.return_value = MagicMock(content="Refined body.")
        rec = propose_skill("do stuff", ["step1"], skills_dir, llm=fake)
        assert rec.body == "Refined body."

    def test_propose_skill_llm_failure_falls_back(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        fake = MagicMock()
        fake.chat.side_effect = RuntimeError("boom")
        rec = propose_skill("do stuff", ["step1"], skills_dir, llm=fake)
        assert "Steps" in rec.body

    def test_propose_skill_conflict_with_promoted(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        registry = MagicMock()
        existing = MagicMock()
        existing.status = "promoted"
        registry.get.side_effect = lambda name: existing if name == "do-stuff" else None
        rec = propose_skill(
            "do stuff", ["step1"], skills_dir, registry=registry
        )
        assert rec.name.startswith("do-stuff-v")


# ========================== skills/hub.py ==========================


class TestHub:
    def test_find_skill_dir_root(self, tmp_path):
        (tmp_path / "SKILL.md").write_text("---\nname: x\n---\n")
        assert _find_skill_dir(tmp_path) == tmp_path

    def test_find_skill_dir_nested(self, tmp_path):
        child = tmp_path / "child"
        child.mkdir()
        (child / "SKILL.md").write_text("---\nname: x\n---\n")
        assert _find_skill_dir(tmp_path) == child

    def test_find_skill_dir_missing(self, tmp_path):
        assert _find_skill_dir(tmp_path) is None

    def test_install_skill_local(self, tmp_path, monkeypatch):
        src = tmp_path / "src"
        src.mkdir()
        (src / "SKILL.md").write_text("---\nname: my-skill\n---\nBody")
        settings = MagicMock()
        settings.skills_dir = tmp_path / "installed"
        settings.skills_dir.mkdir()
        registry = MagicMock()
        registry.get.return_value = None
        name = install_skill(registry, str(src), settings)
        assert name == "my-skill"
        assert (settings.skills_dir / "my-skill").exists()

    def test_install_skill_invalid_location(self, tmp_path):
        settings = MagicMock()
        settings.skills_dir = tmp_path
        registry = MagicMock()
        with pytest.raises(ValueError):
            install_skill(registry, "http://bad.example/notgit", settings)


# ========================== skills/trigger.py ==========================


class TestTrigger:
    def test_keyword_select_skips_deprecated(self):
        registry = MagicMock()
        rec = MagicMock()
        rec.status = "deprecated"
        registry._index = {"old": rec}
        assert keyword_select(registry, "query") == []

    def test_select_returns_empty_without_llm(self):
        registry = MagicMock()
        registry._index = {}
        assert select(registry, "query") == []

    def test_select_llm_fallback_returns_none(self):
        registry = MagicMock()
        registry._index = {}
        fake = MagicMock()
        fake.chat.return_value = MagicMock(content="none")
        assert select(registry, "query", llm=fake) == []

    def test_select_llm_fallback_exception(self):
        registry = MagicMock()
        registry._index = {}
        fake = MagicMock()
        fake.chat.side_effect = RuntimeError("x")
        assert select(registry, "query", llm=fake) == []


# ========================== skills/executable.py ==========================


class DummyRunner:
    def execute(self, **kwargs):
        return "ok"

    def test(self):
        return []


class BrokenRunner:
    def test(self):
        raise RuntimeError("broken")


class TestExecutable:
    def test_is_stale_missing_path(self, tmp_path):
        h = SkillHandle(name="x", path=tmp_path / "missing", runner=None)
        assert h.is_stale() is False

    def test_reload_directory(self, tmp_path):
        runner_file = tmp_path / "runner.py"
        runner_file.write_text("def execute(): return 'hi'\n")
        h = SkillHandle(name="x", path=tmp_path, runner=None)
        h.reload()
        assert h.runner is not None

    def test_reload_file(self, tmp_path):
        runner_file = tmp_path / "single.py"
        runner_file.write_text("def execute(): return 'hi'\n")
        h = SkillHandle(name="x", path=runner_file, runner=None)
        h.reload()
        assert h.runner is not None

    def test_reload_test_failure_collects_error(self, tmp_path):
        runner_file = tmp_path / "runner.py"
        runner_file.write_text("def test(): raise RuntimeError('bad')\n")
        h = SkillHandle(name="x", path=tmp_path, runner=None)
        h.reload()
        assert h.errors == ["test failure: bad"]

    def test_execute_no_execute_method(self):
        h = SkillHandle(name="x", path=Path("/tmp"), runner=object())
        assert "no execute function" in h.execute()

    def test_load_executable_skills_skips_missing(self, tmp_path):
        missing = tmp_path / "missing"
        handles = load_executable_skills([missing])
        assert handles == []

    def test_load_executable_skills_error_path(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("raise RuntimeError('boom')\n")
        handles = load_executable_skills([tmp_path])
        assert len(handles) == 1
        assert handles[0].errors

    def test_run_skill_tests_none_runner(self):
        h = SkillHandle(name="x", path=Path("/tmp"), runner=None)
        assert run_skill_tests(h) == ["not loaded"]

    def test_run_skill_tests_no_test(self):
        h = SkillHandle(name="x", path=Path("/tmp"), runner=DummyRunner())
        assert run_skill_tests(h) == []

    def test_run_skill_tests_exception(self):
        h = SkillHandle(name="x", path=Path("/tmp"), runner=BrokenRunner())
        assert run_skill_tests(h) == ["test exception: broken"]


# ========================== skills/evaluator.py ==========================


class TestEvaluatorGaps:
    def test_decide_refine(self):
        ev = SkillEvaluator(MagicMock())
        d, r = ev._decide(0.7, 0.8, MagicMock(status="candidate"))
        assert d == "refine"

    def test_apply_persists(self, tmp_path):
        rt = make_runtime(tmp_path)
        cand = SkillRecord(
            id="x@0.1.0", name="x", path=tmp_path, version="0.1.0", status="candidate"
        )
        rt.registry._index["x"] = cand
        ev = SkillEvaluator(rt.registry)
        res = ev.evaluate(cand, lambda s, t: RunOutcome(success=True), ["t"])
        ev.apply(res, cand)
        assert rt.registry.get("x").status == "promoted"
        assert rt.registry.get("x").metrics["success_rate"] == 1.0


# ========================== tools/core.py ==========================


class TestCoreTools:
    def test_write_file_success(self, tmp_path):
        tool = WriteFileTool()
        res = tool.run(path=str(tmp_path / "a.txt"), content="hello")
        assert res.ok is True
        assert (tmp_path / "a.txt").read_text() == "hello"

    def test_edit_file_success(self, tmp_path):
        p = tmp_path / "f.txt"
        p.write_text("a b c")
        tool = EditFileTool()
        res = tool.run(path=str(p), old_string="b", new_string="x")
        assert res.ok is True
        assert p.read_text() == "a x c"

    def test_edit_file_missing_old_string(self, tmp_path):
        p = tmp_path / "f.txt"
        p.write_text("a b c")
        tool = EditFileTool()
        res = tool.run(path=str(p), old_string="z", new_string="x")
        assert res.ok is False
        assert "old_string not found" in res.error

    def test_python_exec_syntax_error(self):
        tool = PythonExecTool()
        res = tool.run(code="1 +")
        assert res.ok is False
        assert "syntax error" in res.error

    def test_shell_exec_empty_command(self):
        tool = ShellExecTool()
        res = tool.run(command="")
        assert res.ok is False
        assert "empty command" in res.error

    def test_http_client_success(self, tmp_path, monkeypatch):
        tool = HttpClientTool()
        fake_resp = MagicMock()
        fake_resp.status = 200
        fake_resp.read.return_value = b"hello"
        fake_ctx = MagicMock()
        fake_ctx.__enter__ = MagicMock(return_value=fake_resp)
        fake_ctx.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: fake_ctx)
        res = tool.run(url="http://example.com")
        assert res.ok is True
        assert "hello" in res.output


# ========================== tools/loader.py ==========================


class TestLoader:
    def test_tool_spec_to_tool_shell(self):
        spec = ToolSpec(name="x", description="", command="echo {a}")
        tool = spec.to_tool()
        assert tool.name == "x"

    def test_tool_spec_to_tool_script(self):
        spec = ToolSpec(name="x", description="", script="echo.py")
        tool = spec.to_tool()
        assert tool.name == "x"

    def test_shell_tool_missing_arg(self):
        spec = ToolSpec(name="x", description="", command="echo {a}")
        tool = spec.to_tool()
        res = tool.run(b=1)
        assert res.ok is False
        assert "missing argument" in res.error

    def test_script_tool_missing_file(self):
        spec = ToolSpec(name="x", description="", script="/nonexistent.py")
        tool = spec.to_tool()
        res = tool.run()
        assert res.ok is False
        assert "script not found" in res.error

    def test_load_yaml_spec_missing_name(self, tmp_path):
        p = tmp_path / "t.yaml"
        p.write_text(yaml.safe_dump({"description": "d"}))
        assert _load_yaml_spec(p) is None

    def test_load_json_spec_invalid(self, tmp_path):
        p = tmp_path / "t.json"
        p.write_text("{bad")
        assert _load_json_spec(p) is None

    def test_load_py_spec_docstring(self, tmp_path):
        p = tmp_path / "tool.py"
        p.write_text('"""my tool docstring"""\ndef run(): pass\n')
        spec = _load_py_spec(p)
        assert spec is not None
        assert "my tool docstring" in spec.description

    def test_load_py_spec_comment(self, tmp_path):
        p = tmp_path / "tool.py"
        p.write_text("# simple comment\ndef run(): pass\n")
        spec = _load_py_spec(p)
        assert spec is not None
        assert spec.description == "tool.py"

    def test_load_custom_tools_dir_missing(self, monkeypatch):
        monkeypatch.setattr("pulse.tools.loader.CUSTOM_TOOLS_DIR", Path("/nonexistent"))
        assert load_custom_tools() == []

    def test_list_custom_tool_specs_missing_dir(self, monkeypatch):
        monkeypatch.setattr("pulse.tools.loader.CUSTOM_TOOLS_DIR", Path("/nonexistent"))
        assert list_custom_tool_specs() == []

    def test_load_custom_tools_yaml_script_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pulse.tools.loader.CUSTOM_TOOLS_DIR", tmp_path)
        p = tmp_path / "bad.yaml"
        p.write_text("name: x\nscript: /nonexistent.py\n")
        tools = load_custom_tools()
        assert len(tools) == 0


# ========================== web/server.py ==========================


class TestWebServer:
    def test_create_session(self, tmp_path):
        rt = make_runtime(tmp_path)
        ui = PulseWebUI(rt)
        sid = ui._create_session("test")
        assert sid.startswith("sess_")
        assert ui._get_session(sid)["name"] == "test"

    def test_delete_session(self, tmp_path):
        rt = make_runtime(tmp_path)
        ui = PulseWebUI(rt)
        sid = ui._create_session("test")
        ui._delete_session(sid)
        assert ui._get_session(sid) is None

    def test_get_all_sessions(self, tmp_path):
        rt = make_runtime(tmp_path)
        ui = PulseWebUI(rt)
        ui._create_session("a")
        ui._create_session("b")
        all_s = ui._get_all_sessions()
        assert len(all_s) == 2

    def test_index_route(self, tmp_path):
        rt = make_runtime(tmp_path)
        ui = PulseWebUI(rt)
        client = ui.app.test_client()
        resp = client.get("/")
        assert resp.status_code == 200

    def test_chat_route_missing_session(self, tmp_path):
        rt = make_runtime(tmp_path)
        ui = PulseWebUI(rt)
        client = ui.app.test_client()
        resp = client.get("/chat/doesnotexist")
        assert resp.status_code in (301, 302)

    def test_tools_route(self, tmp_path):
        rt = make_runtime(tmp_path)
        ui = PulseWebUI(rt)
        client = ui.app.test_client()
        resp = client.get("/tools")
        assert resp.status_code == 200

    def test_settings_route(self, tmp_path):
        rt = make_runtime(tmp_path)
        ui = PulseWebUI(rt)
        client = ui.app.test_client()
        resp = client.get("/settings")
        assert resp.status_code == 200

    def test_api_create_session_post_form(self, tmp_path):
        rt = make_runtime(tmp_path)
        ui = PulseWebUI(rt)
        client = ui.app.test_client()
        resp = client.post("/api/sessions", data={"name": "new"})
        assert resp.status_code in (301, 302, 200)

    def test_api_delete_session(self, tmp_path):
        rt = make_runtime(tmp_path)
        ui = PulseWebUI(rt)
        sid = ui._create_session("to-delete")
        resp = client.post(f"/api/sessions/{sid}/delete")
        assert resp.status_code in (301, 302)

    def test_api_chat_no_body(self, tmp_path):
        rt = make_runtime(tmp_path)
        ui = PulseWebUI(rt)
        client = ui.app.test_client()
        resp = client.post("/api/chat", json={})
        assert resp.status_code == 400

    def test_api_tools(self, tmp_path):
        rt = make_runtime(tmp_path)
        ui = PulseWebUI(rt)
        client = ui.app.test_client()
        resp = client.get("/api/tools")
        assert resp.status_code == 200


# ========================== scheduler/cron.py ==========================


class TestCron:
    def test_parse_cron_valid(self):
        assert _parse_cron("0 * * * *") is not None

    def test_parse_cron_invalid(self):
        assert _parse_cron("* * *") is None

    def test_cron_matches_wildcard(self):
        dt = datetime(2024, 1, 1, 12, 0)
        assert _cron_matches("* * * * *", dt) is True

    def test_cron_matches_specific(self):
        dt = datetime(2024, 1, 1, 12, 0)
        assert _cron_matches("0 12 * * *", dt) is True
        assert _cron_matches("0 11 * * *", dt) is False

    def test_cron_matches_range(self):
        dt = datetime(2024, 1, 1, 12, 0)
        assert _cron_matches("0 10-13 * * *", dt) is True

    def test_cron_matches_step(self):
        dt = datetime(2024, 1, 1, 12, 15)
        assert _cron_matches("*/15 * * * *", dt) is True

    def test_parse_natural_hourly(self):
        seconds, expr = parse_natural("hourly")
        assert seconds == 3600
        assert expr == ""

    def test_parse_natural_every_minutes(self):
        seconds, expr = parse_natural("every 10 min")
        assert seconds == 600

    def test_parse_natural_default(self):
        seconds, expr = parse_natural("garbage")
        assert seconds == 3600

    def test_scheduler_add_remove(self):
        s = Scheduler()
        job = s.add("j", 1, lambda: None)
        assert job.name == "j"
        s.remove("j")
        assert s.list() == []

    def test_scheduler_pause_resume(self):
        s = Scheduler()
        s.add("j", 1, lambda: None)
        assert s.pause("j") is True
        assert s.resume("j") is True
        assert s.pause("missing") is False

    def test_scheduler_start_stop(self):
        s = Scheduler()
        s.start()
        assert s._thread is not None
        s.stop()
        assert s._thread is None

    def test_scheduler_run_job_failure(self):
        s = Scheduler()
        history = []

        def bad():
            raise RuntimeError("fail")

        s._run_job(
            Scheduler._loop.__func__  # dummy, below we bypass _loop
        )
        # Use a Job directly
        job = Scheduler.__dataclass_fields__  # dummy, use actual Job
        from pulse.scheduler.cron import Job, JobRun

        job = Job(name="j", interval=0, fn=lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        s._run_job(job)
        assert job.failures == 1
        assert len(s.history) == 1
        assert s.history[0].success is False
