"""Shared runtime assembly for CLI commands."""
from __future__ import annotations

from dataclasses import dataclass

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
    settings: Settings
    storage: Storage
    memory: MemoryStore
    registry: SkillRegistry
    tools: ToolRegistry
    router: Router
    obs: Observability
    orchestrator: Orchestrator


def bootstrap(config_dir=None) -> Runtime:
    settings = load_settings(config_dir)
    storage = Storage(settings.db_path)
    memory = MemoryStore(settings, storage)
    registry = SkillRegistry(settings, storage)
    tools = ToolRegistry()
    register_builtin_tools(tools)
    router = build_router(settings)
    obs = Observability()
    orch = Orchestrator(router, memory, registry, tools, storage, settings, obs)
    return Runtime(settings, storage, memory, registry, tools, router, obs, orch)
