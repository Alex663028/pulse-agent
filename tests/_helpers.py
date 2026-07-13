"""Shared test fixtures: build a fully offline Pulse runtime (mock provider)."""
from __future__ import annotations

from pathlib import Path

from pulse.cli.runtime import Runtime
from pulse.config.settings import ModelSettings, Settings
from pulse.llm.config import build_router
from pulse.llm.provider import MockProvider
from pulse.memory.store import MemoryStore
from pulse.orchestrator.loop import Orchestrator, OrchestratorConfig
from pulse.orchestrator.observability import Observability
from pulse.skills.registry import SkillRegistry
from pulse.storage.engine import Storage
from pulse.tools.builtin import register_builtin_tools
from pulse.tools.registry import ToolRegistry


def make_runtime(tmp_path: Path, provider: str = "mock", model: str = "mock-1") -> Runtime:
    settings = Settings(config_dir=tmp_path, data_dir=tmp_path / "data")
    settings.model = ModelSettings(provider=provider, model=model)
    storage = Storage(settings.db_path)
    memory = MemoryStore(settings, storage)
    registry = SkillRegistry(settings, storage)
    tools = ToolRegistry()
    register_builtin_tools(tools)
    router = build_router(settings)
    obs = Observability()
    orch = Orchestrator(router, memory, registry, tools, storage, settings, obs, config=OrchestratorConfig(auto_evolve=True))
    return Runtime(
        settings=settings, storage=storage, memory=memory, registry=registry,
        tools=tools, router=router, obs=obs, orchestrator=orch,
    )


def flaky_provider(failures: int = 2, model: str = "mock-1"):
    """A provider that fails the first ``failures`` calls with a TRANSIENT error."""

    class Flaky(MockProvider):
        def __init__(self):
            super().__init__(model=model)
            self._n = 0
            self._failures = failures

        def chat(self, messages, tools=None, tool_choice=None, **kwargs):
            self._n += 1
            if self._n <= self._failures:
                from pulse.llm.provider import LLMError

                raise LLMError("503 Service Unavailable (transient)")
            return super().chat(messages, tools=tools, tool_choice=tool_choice, **kwargs)

    return Flaky()
