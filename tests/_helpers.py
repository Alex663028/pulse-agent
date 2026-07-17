"""Shared test fixtures for offline testing.

Provides a lightweight StubProvider that does not make API calls.
For real integration testing, set PULSE_TEST_API_KEY and use provider="openai".
"""
from __future__ import annotations

from pathlib import Path

from pulse.cli.runtime import Runtime
from pulse.config.settings import ModelSettings, Settings
from pulse.llm.provider import LLMMessage, LLMProvider, LLMResponse, ToolCall, Usage
from pulse.memory.store import MemoryStore
from pulse.orchestrator.loop import Orchestrator, OrchestratorConfig
from pulse.orchestrator.observability import Observability
from pulse.skills.registry import SkillRegistry
from pulse.storage.engine import Storage
from pulse.tools.builtin import register_builtin_tools
from pulse.tools.registry import ToolRegistry


class StubProvider(LLMProvider):
    """Minimal provider for offline tests. No API calls.

    Responds with canned responses. Supports scripted tool calls via
    [call:tool_name] pattern in user messages.
    """

    name = "stub"

    def __init__(self, model: str = "stub-1"):
        self.model = model
        self.calls: list[list[LLMMessage]] = []
        self._last_tool: str | None = None
        self._scripted: list[LLMResponse] = []

    def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        import re
        self.calls.append(list(messages))
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        if self._scripted:
            return self._scripted.pop(0)
        if tools:
            m = re.search(r"\[call:([\w\-]+)\]", last_user)
            if m and m.group(1) != self._last_tool:
                self._last_tool = m.group(1)
                return LLMResponse(
                    content="",
                    tool_calls=[ToolCall(id="call_1", name=m.group(1), arguments={"query": last_user})],
                    model=self.model,
                )
        answer = f"Acknowledged: {last_user[:120]}"
        return LLMResponse(
            content=answer,
            model=self.model,
            usage=Usage(prompt_tokens=len(last_user) // 4, completion_tokens=len(answer) // 4),
        )

    def add_scripted_response(self, response: LLMResponse) -> None:
        self._scripted.append(response)


def make_runtime(tmp_path: Path, provider: str = "stub", model: str = "stub-1") -> Runtime:
    """Build a test runtime with StubProvider (no API calls)."""
    settings = Settings(config_dir=tmp_path, data_dir=tmp_path / "data")
    settings.model = ModelSettings(provider="openai", model=model, base_url="http://localhost:9999/v1")
    storage = Storage(settings.db_path)
    memory = MemoryStore(settings, storage)
    registry = SkillRegistry(settings, storage)
    tools = ToolRegistry()
    register_builtin_tools(tools)

    # Create stub provider directly instead of via build_router
    stub = StubProvider(model=model)
    from pulse.llm.router import Router
    router = Router(primary=stub, fallbacks=[])

    obs = Observability()
    orch = Orchestrator(router, memory, registry, tools, storage, settings, obs, config=OrchestratorConfig(auto_evolve=True))
    return Runtime(
        settings=settings, storage=storage, memory=memory, registry=registry,
        tools=tools, router=router, obs=obs, orchestrator=orch,
    )


def flaky_provider(failures: int = 2, model: str = "stub-1"):
    """A provider that fails the first ``failures`` calls with a TRANSIENT error."""

    class Flaky(StubProvider):
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
