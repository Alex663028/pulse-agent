"""Tests for tools/loader.py — ToolSpec, ShellTool, ScriptTool, load functions."""
from __future__ import annotations

import json
from unittest.mock import patch


from pulse.tools.loader import (
    ShellTool,
    ScriptTool,
    ToolSpec,
    _load_json_spec,
    _load_py_spec,
    _load_yaml_spec,
    load_custom_tools,
)


class TestToolSpec:
    """Test ToolSpec dataclass."""

    def test_to_tool_shell(self):
        """ToolSpec.to_tool returns ShellTool when command is set."""
        spec = ToolSpec(
            name="test_tool",
            description="A tool",
            command="echo {text}",
            timeout=10,
        )
        tool = spec.to_tool()
        assert isinstance(tool, ShellTool)
        assert tool.name == "test_tool"
        assert tool.description == "A tool"

    def test_to_tool_script(self):
        """ToolSpec.to_tool returns ScriptTool when script is set."""
        spec = ToolSpec(
            name="test_tool",
            description="A tool",
            script="/path/to/script.py",
            timeout=30,
        )
        tool = spec.to_tool()
        assert isinstance(tool, ScriptTool)


class TestShellTool:
    """Test ShellTool."""

    def test_run_executes_command(self):
        """ShellTool executes shell command."""
        spec = ToolSpec(
            name="echo_tool",
            description="Echo text",
            command="echo {text}",
            timeout=5,
        )
        tool = ShellTool(spec)
        result = tool.run(text="hello")
        assert result.ok is True
        assert "hello" in result.output

    def test_run_missing_argument(self):
        """ShellTool handles missing argument."""
        spec = ToolSpec(
            name="echo_tool",
            description="Echo",
            command="echo {text}",
        )
        tool = ShellTool(spec)
        result = tool.run()
        assert result.ok is False
        assert "missing" in result.error.lower()

    def test_run_no_template(self):
        """ShellTool handles empty template."""
        spec = ToolSpec(
            name="empty_tool",
            description="No command",
        )
        tool = ShellTool(spec)
        result = tool.run()
        assert result.ok is False
        assert "no command template" in result.error.lower()

    def test_run_timeout(self):
        """ShellTool handles timeout."""
        spec = ToolSpec(
            name="slow_tool",
            description="Slow",
            command="sleep 60",
            timeout=1,
        )
        tool = ShellTool(spec)
        result = tool.run()
        assert result.ok is False
        assert "timeout" in result.error.lower()


class TestScriptTool:
    """Test ScriptTool."""

    def test_run_script_not_found(self):
        """ScriptTool handles missing script file."""
        spec = ToolSpec(
            name="missing",
            description="No script",
            script="/nonexistent/script.py",
        )
        tool = ScriptTool(spec)
        result = tool.run()
        assert result.ok is False
        assert "not found" in result.error.lower()

    def test_run_success(self, tmp_path):
        """ScriptTool executes a valid script."""
        script = tmp_path / "myscript.py"
        script.write_text("def run(**kwargs): print('ok')")
        spec = ToolSpec(
            name="myscript",
            description="Test script",
            script=str(script),
            timeout=5,
        )
        tool = ScriptTool(spec)
        result = tool.run()
        assert result.ok is True

    def test_build_wrapper(self, tmp_path):
        """ScriptTool builds a wrapper script."""
        script = tmp_path / "myscript.py"
        script.write_text("def run(**kwargs): return 'hello'")
        spec = ToolSpec(
            name="myscript",
            description="Test",
            script=str(script),
        )
        tool = ScriptTool(spec)
        wrapper = tool._build_wrapper()
        assert "myscript" not in wrapper  # The script function should be inlined
        assert "def run" in wrapper


class TestLoadSpecs:
    """Test _load_yaml_spec, _load_json_spec, _load_py_spec."""

    def test_load_yaml_valid(self, tmp_path):
        """_load_yaml_spec loads valid YAML."""
        f = tmp_path / "tool.yaml"
        f.write_text("name: test_tool\ndescription: A tool\ncommand: echo hello")
        spec = _load_yaml_spec(f)
        assert spec is not None
        assert spec.name == "test_tool"

    def test_load_yaml_no_name(self, tmp_path):
        """_load_yaml_spec returns None if no name."""
        f = tmp_path / "tool.yaml"
        f.write_text("description: No name")
        spec = _load_yaml_spec(f)
        assert spec is None

    def test_load_json_valid(self, tmp_path):
        """_load_json_spec loads valid JSON."""
        f = tmp_path / "tool.json"
        f.write_text(json.dumps({"name": "test_tool", "description": "A tool"}))
        spec = _load_json_spec(f)
        assert spec is not None
        assert spec.name == "test_tool"

    def test_load_json_no_name(self, tmp_path):
        """_load_json_spec returns None if no name."""
        f = tmp_path / "tool.json"
        f.write_text(json.dumps({"description": "No name"}))
        spec = _load_json_spec(f)
        assert spec is None

    def test_load_py_valid(self, tmp_path):
        """_load_py_spec loads a Python file."""
        f = tmp_path / "my_tool.py"
        f.write_text("\"\"\"My custom tool\"\"\"\ndef run(**kwargs): pass")
        spec = _load_py_spec(f)
        assert spec is not None
        assert spec.name == "my_tool"
        assert "My custom tool" in spec.description


class TestLoadCustomTools:
    """Test load_custom_tools function."""

    def test_load_empty_dir(self, tmp_path):
        """load_custom_tools returns empty list for empty dir."""
        with patch("pulse.tools.loader.CUSTOM_TOOLS_DIR", tmp_path):
            tools = load_custom_tools()
            assert tools == []

    def test_load_with_yaml(self, tmp_path):
        """load_custom_tools loads YAML tools."""
        f = tmp_path / "test_tool.yaml"
        f.write_text("name: test_tool\ndescription: Test\ncommand: echo hello")
        with patch("pulse.tools.loader.CUSTOM_TOOLS_DIR", tmp_path):
            tools = load_custom_tools()
            assert len(tools) == 1
            assert tools[0].name == "test_tool"

    def test_load_with_json(self, tmp_path):
        """load_custom_tools loads JSON tools."""
        f = tmp_path / "test_tool.json"
        f.write_text(json.dumps({"name": "test_tool", "description": "Test"}))
        with patch("pulse.tools.loader.CUSTOM_TOOLS_DIR", tmp_path):
            tools = load_custom_tools()
            assert len(tools) == 1
            assert tools[0].name == "test_tool"

    def test_load_skips_invalid(self, tmp_path):
        """load_custom_tools skips invalid files."""
        f = tmp_path / "invalid.yaml"
        f.write_text("not valid yaml: [")
        with patch("pulse.tools.loader.CUSTOM_TOOLS_DIR", tmp_path):
            tools = load_custom_tools()
            assert tools == []
