"""Shared runtime assembly for CLI commands."""
from __future__ import annotations

import logging
import sys
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
    """Container of wired-up services used by CLI/gateway commands."""

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
    """Construct and wire together all Pulse services."""
    settings = load_settings(config_dir)
    _setup_logging(settings.log_level)
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


def _setup_logging(level: str = "INFO") -> None:
    """Configure root pulse logger with stderr handler."""
    lvl = getattr(logging, level.upper(), logging.INFO)
    logger = logging.getLogger("pulse")
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.setLevel(lvl)
    logger.addHandler(handler)
