"""Shared runtime assembly for CLI commands."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pulse.config.settings import Settings, load_settings
from pulse.llm.config import build_router
from pulse.llm.router import Router
from pulse.memory.store import MemoryStore
from pulse.orchestrator.loop import Orchestrator
from pulse.orchestrator.observability import Observability
from pulse.skills.registry import SkillRegistry
from pulse.storage.engine import Storage
from pulse.tools.builtin import register_builtin_tools
from pulse.tools.registry import ToolRegistry


@dataclass
class Runtime:
    """Container of wired-up services (settings, storage, memory, registry, tools, router, orchestrator) used by CLI/gateway commands."""

    settings: Settings
    storage: Storage
    memory: MemoryStore
    registry: SkillRegistry
    tools: ToolRegistry
    router: Router
    obs: Observability
    orchestrator: Orchestrator
    mcp: Any = None


def bootstrap(config_dir=None, load_mcp: bool = False) -> Runtime:
    """Construct and wire together all Pulse services into a single ``Runtime`` instance.

    ``load_mcp`` controls whether configured MCP servers are started and their
    tools registered. It defaults to False so cheap commands (init, doctor,
    config inspection) don't spin up subprocesses; interactive commands pass
    True to make external MCP tools available to the orchestrator.
    """
    settings = load_settings(config_dir)
    storage = Storage(settings.db_path)
    memory = MemoryStore(settings, storage)
    registry = SkillRegistry(settings, storage)
    tools = ToolRegistry()
    register_builtin_tools(tools)
    router = build_router(settings)
    obs = Observability()
    orch = Orchestrator(router, memory, registry, tools, storage, settings, obs)
    rt = Runtime(settings, storage, memory, registry, tools, router, obs, orch)

    manager = None
    if load_mcp and settings.mcp_servers:
        from pulse.mcp import MCPManager

        manager = MCPManager(tools)
        manager.load_servers(settings.mcp_servers)
        rt.mcp = manager

    return rt
