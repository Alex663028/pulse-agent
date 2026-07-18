"""Shared runtime assembly for CLI commands."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import Any, Optional

from pulse.config.settings import Settings, load_settings
from pulse.llm.config import build_router
from pulse.llm.router import Router
from pulse.memory.store import MemoryStore
from pulse.orchestrator.loop import Orchestrator
from pulse.orchestrator.observability import Observability
from pulse.skills.registry import SkillRegistry
from pulse.storage.engine import Storage
from pulse.tools.builtin import register_builtin_tools
from pulse.tools.loader import load_custom_tools
from pulse.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class Runtime:
    settings: Settings
    storage: Storage
    memory: MemoryStore
    registry: SkillRegistry
    tools: ToolRegistry
    router: Router
    obs: Observability
    orchestrator: Orchestrator
    mcp: Any = None


def bootstrap(
    config_dir=None, load_mcp: bool = False, profile: Optional[str] = None
) -> Runtime:
    # Auto-detect profile from env var
    if profile is None:
        profile = os.environ.get("PULSE_PROFILE")
    settings = load_settings(config_dir, profile=profile)
    _setup_logging(settings.log_level)
    storage = Storage(settings.db_path)
    memory = MemoryStore(settings, storage)
    registry = SkillRegistry(settings, storage)
    tools = ToolRegistry()
    register_builtin_tools(tools)
    # Load dynamic tools from ~/.pulse/tools/
    for custom_tool in load_custom_tools():
        tools.register(custom_tool)
    # Load executable skills and register their tools
    from pulse.skills.executable import load_executable_skills

    for handle in load_executable_skills(
        [
            settings.skills_dir,
            settings.config_dir / "skills",
            settings.skills_dir.parent / "skills",
        ],
        tools,
    ):
        if handle.errors:
            logger.warning("skill '%s' failed to load: %s", handle.name, handle.errors)
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
    try:
        from pulse.cli.runtime_ext import apply_extensions

        apply_extensions(rt)
        orch._ext = getattr(rt, "ext", None)
        obs._ext = getattr(rt, "ext", None)
    except Exception as e:
        logger.warning("runtime extensions init failed: %s", e)
    return rt


def _setup_logging(level: str = "INFO") -> None:
    lvl = getattr(logging, level.upper(), logging.INFO)
    logger_root = logging.getLogger("pulse")
    if logger_root.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logger_root.setLevel(lvl)
    logger_root.addHandler(handler)
