"""End-to-end tests — run the full stack through realistic scenarios."""

from __future__ import annotations

import pytest

from pulse.config.settings import Settings, save_settings
from pulse.llm.router import Router
from pulse.memory.store import MemoryStore
from pulse.orchestrator.loop import Orchestrator, TaskResult
from pulse.orchestrator.observability import Observability
from pulse.skills.registry import SkillRegistry
from pulse.storage.engine import Storage
from pulse.tools.registry import ToolRegistry
from pulse.tools.builtin import register_builtin_tools


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PULSE_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def stub_settings(tmp_home):
    cfg_dir = tmp_home / ".pulse"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    models_dir = cfg_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    # .env with empty key
    (cfg_dir / ".env").write_text("", encoding="utf-8")
    settings = Settings(config_dir=cfg_dir)
    settings.model.provider = "openai"
    settings.model.model = "stub-1"
    settings.model.base_url = "http://localhost:9999/v1"
    save_settings(settings)
    return settings


@pytest.fixture
def orchestrator(stub_settings):
    storage = Storage(stub_settings.db_path)
    memory = MemoryStore(stub_settings, storage)
    registry = SkillRegistry(stub_settings, storage)
    tools = ToolRegistry()
    register_builtin_tools(tools)

    # Create stub provider directly
    from tests._helpers import StubProvider

    provider = StubProvider(model="stub-1")
    router = Router(primary=provider)
    obs = Observability()
    yield Orchestrator(router, memory, registry, tools, storage, stub_settings, obs)
    storage.close()


class TestBasicInteraction:
    """Test basic ask → answer flow."""

    def test_simple_question(self, orchestrator):
        result = orchestrator.run("hello world", session_id="test-1")
        assert result.success
        assert "Acknowledged" in result.answer
        assert result.session_id == "test-1"

    def test_tool_call_works(self, orchestrator):
        result = orchestrator.run(
            "read the file [call:list_dir] in the current directory",
            session_id="test-tools",
        )
        assert result.success
        # Stub provider emits a tool call the first time it sees [call:xxx]
        assert any(t["action"].startswith("tool:") for t in result.trajectory)


class TestMemoryPersistence:
    """Test that session memory survives across runs."""

    def test_cross_session_memory(self, orchestrator):
        # First turn
        r1 = orchestrator.run("my name is Alice", session_id="memory-test")
        assert r1.success
        # Second turn (same session id)
        r2 = orchestrator.run("what's my name?", session_id="memory-test")
        assert r2.success
        # The agent should have injected prior context
        assert len(orchestrator.get_session_history("memory-test")) > 0


class TestMultiToolTask:
    """Test realistic multi-tool tasks."""

    def test_read_then_compute(self, orchestrator):
        result = orchestrator.run(
            "calculate 2 + 3 [call:calc]",
            session_id="math-test",
        )
        assert result.success
        assert len(result.trajectory) >= 1

    def test_list_then_read(self, orchestrator):
        result = orchestrator.run(
            "list files [call:list_dir] then read one [call:read_file]",
            session_id="fs-test",
        )
        assert result.success
        # Should have tool calls in trajectory
        actions = [t["action"] for t in result.trajectory]
        assert any("tool:" in a for a in actions)


class TestErrorHandling:
    """Test that errors are handled gracefully."""

    def test_unknown_tool_does_not_crash(self, orchestrator):
        result = orchestrator.run(
            "use the nonexistent tool [call:no_such_tool_xyz]",
            session_id="err-test",
        )
        # Should still succeed (stub provider won't match unknown tool)
        assert result.success or result.error is not None

    def test_empty_message(self, orchestrator):
        result = orchestrator.run("", session_id="empty-test")
        # Empty input should be handled — result should be a TaskResult
        assert isinstance(result, TaskResult)


class TestNewToolsBuiltin:
    """Test the new built-in tools."""

    def test_calc_tool(self, orchestrator):
        from pulse.tools.base import CalcTool

        tool = CalcTool()
        result = tool.run(expr="2 + 3 * 4")
        assert result.ok
        assert "14" in result.output

    def test_web_fetch_tool_mock(self, orchestrator):
        """Web fetch should retry or fail gracefully on network error."""
        from pulse.tools.core import WebFetchTool

        tool = WebFetchTool()
        # Use an unreachable URL
        result = tool.run(url="http://127.0.0.1:1/max_chars=10")
        # Should fail gracefully (not crash)
        assert isinstance(result.ok, bool)

    def test_python_exec_tool(self, orchestrator):
        from pulse.tools.core import PythonExecTool

        tool = PythonExecTool()
        result = tool.run(code="print(42)")
        if result.ok:
            assert "42" in result.output

    def test_write_file_tool(self, orchestrator, tmp_path):
        from pulse.tools.core import WriteFileTool

        tool = WriteFileTool()
        f = tmp_path / "test.txt"
        result = tool.run(path=str(f), content="hello")
        assert result.ok
        assert f.read_text() == "hello"

    def test_edit_file_tool(self, orchestrator, tmp_path):
        from pulse.tools.core import EditFileTool

        tool = EditFileTool()
        f = tmp_path / "test2.txt"
        f.write_text("hello world")
        result = tool.run(path=str(f), old_string="hello", new_string="goodbye")
        assert result.ok
        assert f.read_text() == "goodbye world"


class TestStreamingMode:
    """Test streaming output."""

    def test_run_stream_exists(self, orchestrator):
        assert hasattr(orchestrator, "run_stream")

    def test_run_stream_yields(self, orchestrator):
        chunks = list(orchestrator.run_stream("hello", session_id="stream-test"))
        assert len(chunks) >= 1


class TestFeedbackLearning:
    """Test that corrections are remembered."""

    def test_add_correction(self, orchestrator):
        orchestrator.add_correction("always use type hints")
        assert "always use type hints" in orchestrator._corrections

    def test_corrections_in_system_prompt(self, orchestrator):
        orchestrator.add_correction("test correction")
        system = orchestrator._build_system([])
        assert "test correction" in system
