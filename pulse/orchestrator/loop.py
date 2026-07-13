"""Core orchestration loop (reliability-first).

Ties together the LLM router, memory, skills, tools and storage, and wraps
every step in the recovery + context-budget guardrails. This is where Pulse's
three priority fixes come together:
  * reliability  -> guarded LLM/tool calls, error classification, ctx budget
  * memory       -> MEMORY.md + FTS5 recall injected into the system prompt
  * skill loop   -> after a complex success, propose a candidate skill
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import uuid4

from pulse.config.settings import Settings
from pulse.llm.provider import LLMMessage
from pulse.llm.router import Router
from pulse.memory.store import MemoryStore
from pulse.orchestrator.context_budget import ContextBudget
from pulse.orchestrator.observability import Observability
from pulse.orchestrator.recovery import CtxOverflowError, ErrorClass, classify, guarded
from pulse.skills.evolution import propose_skill
from pulse.skills.registry import SkillRegistry
from pulse.skills.trigger import select as select_skills
from pulse.storage.engine import Storage
from pulse.tools.registry import ToolRegistry


def _est(text: str) -> int:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    return max(1, cjk + (len(text) - cjk) // 4)


@dataclass
class OrchestratorConfig:
    max_iterations: int = 8
    auto_evolve: bool = True


@dataclass
class TaskResult:
    success: bool
    answer: str = ""
    used_skills: list[str] = field(default_factory=list)
    trajectory: list[dict[str, Any]] = field(default_factory=list)
    token_usage: int = 0
    session_id: str = ""
    trace_id: str = ""
    candidate_skill: Optional[str] = None
    error: Optional[str] = None


SYSTEM_PROMPT = (
    "You are Pulse, a reliable self-improving personal assistant. "
    "Follow instructions precisely. When a tool is available and needed, call it. "
    "Keep answers concise and factual."
)


class Orchestrator:
    def __init__(
        self,
        router: Router,
        memory: MemoryStore,
        registry: SkillRegistry,
        tools: ToolRegistry,
        storage: Storage,
        settings: Settings,
        obs: Optional[Observability] = None,
        config: Optional[OrchestratorConfig] = None,
    ):
        self.router = router
        self.memory = memory
        self.registry = registry
        self.tools = tools
        self.storage = storage
        self.settings = settings
        self.obs = obs or Observability()
        self.config = config or OrchestratorConfig()

    def _build_system(self, skills: list) -> str:
        parts = [SYSTEM_PROMPT]
        mem = self.memory.read_memory().strip()
        if mem:
            parts.append(f"## Memory (MEMORY.md)\n{mem[:1500]}")
        if skills:
            sk = "\n\n".join(f"### {s.title}\n{s.description}\n{s.body[:600]}" for s in skills)
            parts.append(f"## Available skills\n{sk}")
        return "\n\n".join(parts)

    def _total_tokens(self, messages: list[LLMMessage]) -> int:
        return sum(_est(m.content) + sum(_est(tc.arguments.__str__()) for tc in m.tool_calls) for m in messages)

    def run(self, task: str, session_id: Optional[str] = None) -> TaskResult:
        sid = session_id or f"sess:{uuid4().hex[:12]}"
        self.obs.emit("session_start", session=sid, task=task[:200])
        self.storage.index_memory(sid, task)

        skills = select_skills(self.registry, task, llm=self.router.primary if self.settings.model.provider == "mock" else None)
        for s in skills:
            self.obs.skill_activated(s.name)

        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=self._build_system(skills)),
            LLMMessage(role="user", content=task),
        ]
        budget = ContextBudget(max_tokens=self.settings.max_session_tokens)
        result = TaskResult(success=False, session_id=sid, trace_id=self.obs.trace_id)
        tool_schemas = self.tools.schemas()

        for step in range(self.config.max_iterations):
            # context guardrail
            if budget.over_soft:
                compacted = budget.fit("\n".join(m.content for m in messages), keep_tokens=self.settings.max_session_tokens // 4, llm=self.router.primary)
                messages = [messages[0], LLMMessage(role="user", content=f"[context compacted]\n{compacted}")]
            try:
                resp = guarded(
                    self.router.chat,
                    messages,
                    tools=tool_schemas or None,
                    allow=(ErrorClass.TRANSIENT,),
                )
            except CtxOverflowError:
                compacted = budget.fit("\n".join(m.content for m in messages), keep_tokens=self.settings.max_session_tokens // 4, llm=self.router.primary)
                messages = [messages[0], LLMMessage(role="user", content=f"[context compacted]\n{compacted}")]
                continue
            except Exception as e:  # noqa: BLE001
                self.obs.error(classify(e), str(e))
                result.error = f"[{classify(e)}] {e}"
                return result

            budget.reserve(resp.usage.total or _est(resp.content))
            self.obs.token_usage(resp.usage.prompt_tokens, resp.usage.completion_tokens, budget.used)

            if resp.tool_calls:
                messages.append(LLMMessage(role="assistant", content=resp.content, tool_calls=resp.tool_calls))
                for tc in resp.tool_calls:
                    r = self.tools.call(tc.name, tc.arguments)
                    self.obs.tool_called(tc.name, r.ok, r.error or "")
                    result.trajectory.append({"action": f"tool:{tc.name}", "detail": tc.arguments, "outcome": r.ok})
                    messages.append(
                        LLMMessage(role="tool", name=tc.name, tool_call_id=tc.id, content=r.output or r.error or "")
                    )
                continue
            # final answer
            result.success = True
            result.answer = resp.content
            result.used_skills = [s.name for s in skills]
            result.token_usage = budget.used
            self.storage.store_session(sid, summary=resp.content[:200], token_usage=budget.used)
            self.storage.log_trajectory(
                tid=f"traj:{uuid4().hex[:10]}",
                session_id=sid,
                outcome=True,
                used_skills=result.used_skills,
                data={"task": task, "trajectory": result.trajectory, "answer": resp.content},
            )
            # self-evolution: propose a candidate skill after a complex success
            if self.config.auto_evolve and result.trajectory:
                steps = [t["detail"].get("query") or t["action"] for t in result.trajectory]
                rec = propose_skill(task, [str(s) for s in steps], self.settings.skills_dir)
                self.registry.register(rec)
                result.candidate_skill = rec.name
                self.obs.emit("skill_proposed", skill=rec.name)
            return result

        result.error = "max iterations reached without a final answer"
        return result
