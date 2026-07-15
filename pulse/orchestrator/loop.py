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
    """Estimate token count from text (~3.2 chars/token, ~1.6 chars/token for CJK)."""
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    return max(1, cjk * 2 + (len(text) - cjk * 2) // 3)


@dataclass
class OrchestratorConfig:
    """Tunables for the orchestration loop (max iterations, self-evolution toggle)."""

    max_iterations: int = 20  # bumped from 8 — complex multi-tool tasks need more steps
    auto_evolve: bool = True


@dataclass
class TaskResult:
    """Final outcome of an orchestration run: answer, trajectory, tokens and optional error."""

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
    """Core agent loop tying LLM, memory, skills, tools and storage behind recovery + budget guardrails."""

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
            # Only inject skill name + description to save context; full body loaded on demand
            sk_lines = []
            for s in skills:
                sk_lines.append(f"- **{s.name}**: {s.description[:200]}")
            parts.append(f"## Available skills\n{chr(10).join(sk_lines)}")
        return "\n\n".join(parts)

    def _compact_messages(self, messages: list[LLMMessage], keep_tokens: int) -> list[LLMMessage]:
        """Compact messages while preserving the system prompt and recent tool results.

        Strategy: keep system prompt + keep most recent ``keep_n`` messages,
        summarize the rest. This preserves tool call results and conversation
        flow that a naive text join would lose.
        """
        keep_n = 6  # keep last 6 messages as-is (covers system + recent turns)
        if len(messages) <= keep_n:
            return messages
        # Keep system prompt + recent messages
        kept = messages[:1] + messages[-(keep_n - 1):]
        # Summarize older messages
        older_messages = messages[1:-keep_n + 1] if len(messages) > keep_n else messages[1:]
        older_text = "\n".join(m.content for m in older_messages if m.content)
        if not older_text:
            return kept
        # Use LLM summary via Router (fallback chain + rate limiter)
        if self.router.primary:
            try:
                resp = self.router.chat([
                    LLMMessage(role="system", content="Summarize the following conversation history into a concise brief. Keep key decisions, tool results, and facts. Be brief."),
                    LLMMessage(role="user", content=older_text[:8000]),
                ], max_tokens=keep_tokens // 4)
                summary = resp.content or f"[summarized {len(older_messages)} older messages]"
            except Exception:
                summary = f"[summarized {len(older_messages)} older messages]"
        else:
            summary = f"[summarized {len(older_messages)} older messages]"
        # Insert summary between system prompt and recent messages
        summary_msg = LLMMessage(role="user", content="[context compacted]\n" + summary)
        return [kept[0], summary_msg, *kept[1:]]

    def _total_tokens(self, messages: list[LLMMessage]) -> int:
        return sum(_est(m.content) + sum(_est(tc.arguments.__str__()) for tc in m.tool_calls) for m in messages)

    def run(self, task: str, session_id: Optional[str] = None) -> TaskResult:
        """Run ``task`` to completion (or until max iterations), returning a TaskResult."""
        sid = session_id or f"sess:{uuid4().hex[:12]}"
        self.obs.emit("session_start", session=sid, task=task[:200])
        self.storage.index_memory(sid, task)

        try:
            skills = select_skills(self.registry, task, llm=self.router.primary if self.settings.model.provider == "mock" else None)
        except Exception:  # skill selection is non-critical — proceed without
            skills = []
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
            # context guardrail — compact only old messages, keep recent tool results
            if budget.over_soft:
                messages = self._compact_messages(messages, keep_tokens=self.settings.max_session_tokens // 4)
            try:
                resp = guarded(
                    self.router.chat,
                    messages,
                    tools=tool_schemas or None,
                    allow=(ErrorClass.TRANSIENT,),
                )
            except CtxOverflowError:
                messages = self._compact_messages(messages, keep_tokens=self.settings.max_session_tokens // 4)
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
            # self-evolution: only propose a candidate skill after a complex success
            # skip trivial runs: single tool call or no tools used produces low-quality skills
            if self.config.auto_evolve and len(result.trajectory) >= 3:
                tool_actions = {t.get("action", "") for t in result.trajectory if t.get("action")}
                if len(tool_actions) >= 2:  # used 2+ distinct tools
                    steps = [t["detail"].get("query") or t["action"] for t in result.trajectory]
                    rec = propose_skill(task, [str(s) for s in steps], self.settings.skills_dir, llm=self.router.primary, registry=self.registry)
                    self.registry.register(rec)
                    result.candidate_skill = rec.name
                    self.obs.emit("skill_proposed", skill=rec.name)
            return result

        result.error = "max iterations reached without a final answer"
        return result
