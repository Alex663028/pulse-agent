"""M5 tests: plugin loading + multi-agent team orchestration."""
from __future__ import annotations

import uuid
from pathlib import Path

from pulse.plugins.loader import PluginLoader
from pulse.team.orchestrator import TeamOrchestrator
from tests._helpers import make_runtime


# ---- plugin system ----
def _add_plugin(plugins_dir: Path, name: str, content: str) -> Path:
    plugins_dir.mkdir(parents=True, exist_ok=True)
    p = plugins_dir / f"{name}.py"
    p.write_text(content)
    return p


WEATHER_PLUGIN = '''"""description="mock weather tool" """
from pulse.tools.base import Tool, ToolResult

class WeatherTool(Tool):
    name = "get_weather"
    description = "Get weather for a city. Args: city."
    parameters = {"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}
    def run(self, city="", **kw):
        return ToolResult(ok=True, output=f"Sunny, 22C in {city}")

def register(runtime):
    runtime.tools.register(WeatherTool())
'''


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
    activated = pl.activate(rt, names=["weather"])
    assert "weather" in activated, f"activated: {activated}"
    assert rt.tools.get("get_weather") is not None


def test_plugin_activate_nonexistent():
    rt = make_runtime(Path("/tmp") / f"pulse_m5_plug3_{uuid.uuid4().hex}")
    pl = PluginLoader(rt.settings.config_dir / "plugins")
    activated = pl.activate(rt, names=["no-such-plugin"])
    assert activated == []


# ---- multi-agent team ----
def test_team_run_mock():
    rt = make_runtime(Path("/tmp") / f"pulse_m5_team_{uuid.uuid4().hex}")
    tm = TeamOrchestrator(max_rounds=2, max_workers=2)
    result = tm.run(
        "research async Python patterns, draft a best-practices summary",
        primary=rt.router.primary,
        tools=rt.tools,
    )
    # with mock provider, short tasks should pass reviewer
    assert len(result.builder_results) >= 1
    assert len(result.answer) > 0


def test_team_single_subtask():
    rt = make_runtime(Path("/tmp") / f"pulse_m5_team2_{uuid.uuid4().hex}")
    tm = TeamOrchestrator(max_rounds=2, max_workers=2)
    result = tm.run("hello", primary=rt.router.primary)
    assert len(result.builder_results) >= 1
