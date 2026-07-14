"""M5 tests: plugin loading (with sandbox) + multi-agent team orchestration."""

from __future__ import annotations

import uuid
from pathlib import Path

from pulse.plugins.loader import PluginLoader
from pulse.plugins.sandbox import (
    PluginSandbox,
    _module_allowed,
    parse_permissions_declaration,
)
from pulse.team.orchestrator import TeamOrchestrator
from tests._helpers import make_runtime


# ---- helpers ----
def _add_plugin(plugins_dir: Path, name: str, content: str) -> Path:
    plugins_dir.mkdir(parents=True, exist_ok=True)
    p = plugins_dir / f"{name}.py"
    p.write_text(content)
    return p


WEATHER_PLUGIN = '''"""description="mock weather tool" """
__permissions__ = ["tools.register", "memory.write"]

from pulse.tools.base import Tool, ToolResult


class WeatherTool(Tool):
    name = "get_weather"
    description = "Get weather for a city. Args: city."
    parameters = {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    }

    def run(self, city="", **kw):
        return ToolResult(ok=True, output=f"Sunny, 22C in {city}")


def register(runtime):
    runtime.tools.register(WeatherTool())
'''


# ---- plugin discovery ----
def test_plugin_discover_bundled():
    rt = make_runtime(Path("/tmp") / f"pulse_m5_plug_{uuid.uuid4().hex}")
    plugins_dir = rt.settings.config_dir / "plugins"
    _add_plugin(plugins_dir, "weather", WEATHER_PLUGIN)
    pl = PluginLoader(plugins_dir)
    plugins = pl.discover()
    names = [p.name for p in plugins]
    assert "weather" in names, f"found: {names}"


def test_plugin_activate():
    rt = make_runtime(Path("/tmp") / f"pulse_m5_plug2_{uuid.uuid4().hex}")
    plugins_dir = rt.settings.config_dir / "plugins"
    _add_plugin(plugins_dir, "weather", WEATHER_PLUGIN)
    pl = PluginLoader(plugins_dir)
    activated = pl.activate(rt, names=["weather"], extra_permissions={"memory.write"})
    assert "weather" in activated, f"activated: {activated}"
    assert rt.tools.get("get_weather") is not None


def test_plugin_activate_nonexistent():
    rt = make_runtime(Path("/tmp") / f"pulse_m5_plug3_{uuid.uuid4().hex}")
    pl = PluginLoader(rt.settings.config_dir / "plugins")
    activated = pl.activate(rt, names=["no-such-plugin"])
    assert activated == []


# ---- sandbox ----
def test_sandbox_module_whitelist_allows_safe():
    assert _module_allowed("json") is True
    assert _module_allowed("collections") is True
    assert _module_allowed("pathlib") is True
    assert _module_allowed("pulse.tools.base") is True


def test_sandbox_module_whitelist_denies_dangerous():
    assert _module_allowed("os") is False
    assert _module_allowed("subprocess") is False
    assert _module_allowed("socket") is False
    assert _module_allowed("ctypes") is False
    assert _module_allowed("shutil") is False
    assert _module_allowed("os.path") is False  # submodule of denied


def test_sandbox_module_whitelist_denies_unknown():
    assert _module_allowed("requests") is False
    assert _module_allowed("numpy") is False
    assert _module_allowed("pandas") is False


def test_parse_permissions_declaration():
    src = '''"""A test plugin."""
__permissions__ = ["tools.register", "memory.read"]
'''
    perms = parse_permissions_declaration(src)
    assert perms == {"tools.register", "memory.read"}


def test_parse_permissions_declaration_empty():
    src = '''"""No permissions."""
x = 1
'''
    perms = parse_permissions_declaration(src)
    assert perms == set()


def test_parse_permissions_declaration_single():
    src = '__permissions__ = ["tools.register"]'
    perms = parse_permissions_declaration(src)
    assert perms == {"tools.register"}


def test_sandbox_exec_safe_plugin(tmp_path):
    """A plugin that only uses safe imports should load fine."""
    plugin_code = '''"""Safe plugin."""
__permissions__ = ["tools.register"]

def register(runtime):
    import json  # allowed
    runtime.memory.add_note("safe plugin loaded " + json.dumps({"ok": True}))
'''
    path = tmp_path / "safe_plugin.py"
    path.write_text(plugin_code)
    sandbox = PluginSandbox(granted_permissions={"tools.register", "memory.write"})
    mod = sandbox.exec_module("safe_plugin", path)
    assert hasattr(mod, "register")
    assert mod.__permissions__ == ["tools.register"]


def test_sandbox_denies_dangerous_import(tmp_path):
    """A plugin that imports os at module level should raise ImportError."""
    plugin_code = '''"""Dangerous plugin."""
__permissions__ = ["tools.register"]
import os  # denied at module level
'''
    path = tmp_path / "dangerous_plugin.py"
    path.write_text(plugin_code)
    sandbox = PluginSandbox(granted_permissions={"tools.register"})
    try:
        sandbox.exec_module("dangerous_plugin", path)
        assert False, "should have raised"
    except ImportError:
        pass  # expected


def test_sandbox_denies_missing_permissions(tmp_path):
    """A plugin that declares permissions not granted should raise PermissionError."""
    plugin_code = '''"""Needs extra perms."""
__permissions__ = ["tools.register", "network"]

def register(runtime):
    pass
'''
    path = tmp_path / "needy_plugin.py"
    path.write_text(plugin_code)
    sandbox = PluginSandbox(granted_permissions={"tools.register"})
    try:
        sandbox.exec_module("needy_plugin", path)
        assert False, "should have raised PermissionError"
    except PermissionError:
        pass  # expected


def test_sandbox_has_permission():
    sandbox = PluginSandbox(granted_permissions={"tools.register", "memory.read"})
    assert sandbox.has_permission("tools.register") is True
    assert sandbox.has_permission("network") is False


def test_user_plugin_gets_conservative_perms():
    rt = make_runtime(Path("/tmp") / f"pulse_m5_sbperm_{uuid.uuid4().hex}")
    plugins_dir = rt.settings.config_dir / "plugins"
    _add_plugin(plugins_dir, "weather", WEATHER_PLUGIN)
    pl = PluginLoader(plugins_dir)
    pl.discover()
    info = pl.plugins.get("weather")
    assert info is not None
    assert info.bundled is False
    assert "tools.register" in info.permissions


# ---- multi-agent team ----
def test_team_run_mock():
    rt = make_runtime(Path("/tmp") / f"pulse_m5_team_{uuid.uuid4().hex}")
    tm = TeamOrchestrator(max_rounds=2, max_workers=2)
    result = tm.run(
        "research async Python patterns, draft a best-practices summary",
        primary=rt.router.primary,
        tools=rt.tools,
    )
    assert len(result.builder_results) >= 1
    assert len(result.answer) > 0


def test_team_single_subtask():
    rt = make_runtime(Path("/tmp") / f"pulse_m5_team2_{uuid.uuid4().hex}")
    tm = TeamOrchestrator(max_rounds=2, max_workers=2)
    result = tm.run("hello", primary=rt.router.primary)
    assert len(result.builder_results) >= 1
