"""MCP integration tests: client, tool adapter, manager, and CLI commands."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from pulse.config.settings import MCPServerConfig, Settings
from pulse.mcp import MCPClient, MCPManager, MCPTool
from pulse.tools.base import ToolResult
from pulse.tools.registry import ToolRegistry

FIXTURE = str(Path(__file__).parent / "fixtures" / "mock_mcp_server.py")
PY = sys.executable


@pytest.fixture
def client():
    c = MCPClient(command=PY, args=[FIXTURE], timeout=10)
    c.start()
    yield c
    c.stop()


def test_client_initialize_and_info(client):
    assert client.server_info.get("name") == "mock-mcp"


def test_client_list_tools(client):
    specs = client.list_tools()
    names = {s["name"] for s in specs}
    assert names == {"echo", "reverse"}


def test_client_call_tool(client):
    result = client.call_tool("echo", {"msg": "hello mcp"})
    assert result["isError"] is False
    assert result["content"][0]["text"] == "hello mcp"


def test_client_call_unknown_tool(client):
    result = client.call_tool("nope", {})
    assert result["isError"] is True


def test_mcptool_adapter(client):
    specs = client.list_tools()
    echo_spec = next(s for s in specs if s["name"] == "echo")
    tool = MCPTool(client, echo_spec, server_name="mock")
    assert tool.name == "echo"
    assert "echo" in tool.description.lower()
    # to_schema renders OpenAI-compatible function schema
    schema = tool.to_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "echo"
    # run proxies to the server
    res = tool.run(msg="ping")
    assert isinstance(res, ToolResult)
    assert res.ok is True
    assert res.output == "ping"


def test_mcptool_error_result(client):
    specs = client.list_tools()
    bad_spec = next(s for s in specs if s["name"] == "reverse")
    tool = MCPTool(client, bad_spec)
    # reverse of "abc" is "cba"
    res = tool.run(text="abc")
    assert res.ok is True
    assert res.output == "cba"


def test_manager_registers_prefixed_tools():
    reg = ToolRegistry()
    mgr = MCPManager(reg)
    cfg = MCPServerConfig(name="demo", command=PY, args=[FIXTURE], enabled=True)
    n = mgr.load_servers([cfg])
    assert n == 2
    # tool names are prefixed with server name
    assert reg.get("demo__echo") is not None
    assert reg.get("demo__reverse") is not None
    # calling through the registry works
    res = reg.call("demo__echo", {"msg": "via registry"})
    assert res.ok and res.output == "via registry"
    mgr.shutdown()


def test_manager_skips_disabled():
    reg = ToolRegistry()
    mgr = MCPManager(reg)
    cfg = MCPServerConfig(name="off", command=PY, args=[FIXTURE], enabled=False)
    n = mgr.load_servers([cfg])
    assert n == 0
    mgr.shutdown()


def test_manager_handles_bad_server():
    reg = ToolRegistry()
    mgr = MCPManager(reg)
    # command that does not exist should be skipped gracefully
    cfg = MCPServerConfig(name="broken", command="this_command_does_not_exist_xyz", args=[], enabled=True)
    n = mgr.load_servers([cfg])
    assert n == 0
    mgr.shutdown()


def test_settings_persist_mcp_servers(tmp_path):
    s = Settings(config_dir=tmp_path)
    s.mcp_servers.append(MCPServerConfig(name="fs", command="npx", args=["-y", "@modelcontextprotocol/server-filesystem"]))
    from pulse.config.settings import save_settings, load_settings

    save_settings(s)
    reloaded = load_settings(tmp_path)
    assert len(reloaded.mcp_servers) == 1
    assert reloaded.mcp_servers[0].name == "fs"
    assert reloaded.mcp_servers[0].args == ["-y", "@modelcontextprotocol/server-filesystem"]


def test_cli_mcp_add_and_list(tmp_path):
    from pulse.cli.mcp_cli import cmd_add, cmd_list
    from pulse.config.settings import load_settings

    s = load_settings(tmp_path)
    cmd_add(s, "demo", "python", ["-m", "mock"])
    reloaded = load_settings(tmp_path)
    assert any(x.name == "demo" for x in reloaded.mcp_servers)
    # list should not raise
    cmd_list(reloaded)


def test_cli_mcp_remove(tmp_path):
    from pulse.cli.mcp_cli import cmd_add, cmd_remove
    from pulse.config.settings import load_settings

    s = load_settings(tmp_path)
    cmd_add(s, "demo", "python", ["-m", "mock"])
    cmd_remove(load_settings(tmp_path), "demo")
    reloaded = load_settings(tmp_path)
    assert not any(x.name == "demo" for x in reloaded.mcp_servers)


def test_cli_mcp_export(tmp_path, capsys):
    from pulse.cli.mcp_cli import cmd_add, cmd_export
    from pulse.config.settings import load_settings

    s = load_settings(tmp_path)
    cmd_add(s, "demo", "python", ["-m", "mock"])
    cmd_export(load_settings(tmp_path))
    out = capsys.readouterr().out
    assert "demo" in out
    assert "python" in out


def test_load_settings_preserves_config_dir(tmp_path):
    """Regression: a Settings loaded from an existing config file must keep
    the requested config_dir, otherwise later save_settings() writes to the
    wrong location (the default ~/.pulse) and changes are lost on reload."""
    from pulse.config.settings import load_settings, save_settings

    s = Settings(config_dir=tmp_path)
    s.mcp_servers.append(MCPServerConfig(name="demo", command="python", args=["-m", "mock"]))
    save_settings(s)

    reloaded = load_settings(tmp_path)
    assert reloaded.config_dir.resolve() == tmp_path.resolve()

    # A subsequent save must land in tmp_path, not the default dir.
    reloaded.mcp_servers = []
    save_settings(reloaded)
    assert (tmp_path / "config.yaml").exists()
    assert not any(x.name == "demo" for x in load_settings(tmp_path).mcp_servers)


def test_client_context_manager():
    from pulse.mcp import MCPClient

    # `with` should start, expose tools, and stop cleanly.
    with MCPClient(command=PY, args=[FIXTURE]) as c:
        assert c.server_info.get("name") == "mock-mcp"
        assert {s["name"] for s in c.list_tools()} == {"echo", "reverse"}
    assert c._proc is None  # stopped on exit


def test_doctor_reports_mcp_tools(tmp_path):
    """`pulse doctor` should probe enabled MCP servers and skip disabled ones."""
    from pulse.cli.doctor import run_doctor

    s = Settings(config_dir=tmp_path)
    s.mcp_servers.append(MCPServerConfig(name="mock", command=PY, args=[FIXTURE], enabled=True))
    s.mcp_servers.append(MCPServerConfig(name="off", command="npx", args=["-y", "x"], enabled=False))
    from pulse.config.settings import load_settings, save_settings

    save_settings(s)

    checks = {c.name: c for c in run_doctor(load_settings(tmp_path))}
    assert checks["mcp:mock"].ok is True
    assert "tool" in checks["mcp:mock"].detail
    assert checks["mcp:off"].ok is True
    assert checks["mcp:off"].detail == "disabled"


def test_cli_mcp_add_parses_quoted_invocation(tmp_path):
    """`pulse mcp add` must shell-split a single quoted invocation so flags
    like -y are preserved as args rather than parsed as CLI options."""
    from typer.testing import CliRunner

    from pulse.cli.main import app
    from pulse.config.settings import load_settings

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["mcp", "add", "fs", "npx -y @modelcontextprotocol/server-filesystem /tmp"],
        env={**os.environ, "PULSE_HOME": str(tmp_path)},
    )
    assert result.exit_code == 0, result.output
    servers = load_settings(tmp_path).mcp_servers
    assert any(s.name == "fs" and s.command == "npx" and "-y" in s.args for s in servers)
