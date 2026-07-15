"""Core orchestration loop."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional
from uuid import uuid4

from pulse.config.settings import Settings
from pulse.llm.provider import LLMMessage, LLMResponse
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
    return max(1, cjk * 2 + (len(text) - cjk * 2) // 3)


DANGEROUS_TOOLS = {"write_file", "edit_file", "shell_exec", "python_exec"}


@dataclass
class OrchestratorConfig:
    max_iterations: int = 20
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
    "For complex tasks, first plan your steps, then execute them one at a time. "
    "Verify the results of each step before moving on. "
    "Keep answers concise and factual."
)


class Orchestrator:
    """Core agent loop: reliability-first orchestration + session memory + streaming."""

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
        self._session_histories: dict[str, list[LLMMessage]] = {}
        # User feedback: corrections → injected into memory
        self._corrections: list[str] = []

    def _build_system(self, skills: list) -> str:
        parts = [SYSTEM_PROMPT]
        mem = self.memory.read_memory().strip()
        if mem:
            parts.append(f"## Memory (MEMORY.md)\n{mem[:1500]}")
        if skills:
            sk_lines = [f"- **{s.name}**: {s.description[:200]}" for s in skills]
            parts.append(f"## Available skills\n{chr(10).join(sk_lines)}")
        # Inject recent corrections as lessons
        if self._corrections:
            recent = self._corrections[-5:]
            parts.append("## Recent lessons:\n" + "\n".join(f"- {c}" for c in recent))
        return "\n\n".join(parts)

    def add_correction(self, correction: str) -> None:
        """Record a user correction ('No, I meant X', 'That's wrong because Y')."""
        self._corrections.append(correction.strip())

    def _confirm_if_dangerous(self, name: str, args: dict) -> Optional[str]:
        if name in DANGEROUS_TOOLS:
            self.obs.emit("safety_check", tool=name, args=args, status="auto_confirmed")
            return f"[safety] tool '{name}' will modify filesystem, args={dict(list(args.items())[:3])}"
        return None

    def _compact_messages(self, messages: list[LLMMessage], keep_tokens: int) -> list[LLMMessage]:
        keep_n = 6
        if len(messages) <= keep_n:
            return messages
        kept = messages[:1] + messages[-(keep_n - 1):]
        older_messages = messages[1:-keep_n + 1] if len(messages) > keep_n else messages[1:]
        older_text = "\n".join(m.content for m in older_messages if m.content)
        if not older_text:
            return kept
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
        return [kept[0], LLMMessage(role="user", content="[context compacted]\n" + summary), *kept[1:]]

    def _total_tokens(self, messages: list[LLMMessage]) -> int:
        return sum(_est(m.content) + sum(_est(str(tc.arguments)) for tc in m.tool_calls) for m in messages)

    def run(self, task: str, session_id: Optional[str] = None) -> TaskResult:
        """Run a task to completion and return TaskResult."""
        sid = session_id or f"sess:{uuid4().hex[:12]}"
        return self._run_internal(task, sid, use_streaming=False)

    def run_stream(self, task: str, session_id: Optional[str] = None) -> Iterator[LLMResponse]:
        """Run a task with streaming responses (yields chunks)."""
        sid = session_id or f"sess:{uuid4().hex[:12]}"
        yield from self._run_internal_streaming(task, sid)

    def _run_internal(self, task: str, sid: str, use_streaming: bool = False) -> TaskResult:
        self.obs.emit("session_start", session=sid, task=task[:200])
        self.storage.index_memory(sid, task)
        try:
            skills = select_skills(self.registry, task)
        except Exception:
            skills = []
        for s in skills:
            self.obs.skill_activated(s.name)

        system_content = self._build_system(skills)
        history = self._session_histories.get(sid)
        if history and sid in self._session_histories:
            messages: list[LLMMessage] = history + [LLMMessage(role="user", content=task)]
        else:
            messages = [LLMMessage(role="system", content=system_content), LLMMessage(role="user", content=task)]

        budget = ContextBudget(max_tokens=self.settings.max_session_tokens)
        result = TaskResult(success=False, session_id=sid, trace_id=self.obs.trace_id)
        tool_schemas = self.tools.schemas()

        for step in range(self.config.max_iterations):
            if budget.over_soft:
                messages = self._compact_messages(messages, keep_tokens=self.settings.max_session_tokens // 4)
            try:
                resp = guarded(self.router.chat, messages, tools=tool_schemas or None, allow=(ErrorClass.TRANSIENT,))
            except CtxOverflowError:
                messages = self._compact_messages(messages, keep_tokens=self.settings.max_session_tokens // 4)
                continue
            except Exception as e:
                self.obs.error(classify(e), str(e))
                result.error = f"[{classify(e)}] {e}"
                return result

            budget.reserve(resp.usage.total or _est(resp.content))
            self.obs.token_usage(resp.usage.prompt_tokens, resp.usage.completion_tokens, budget.used)

            if resp.tool_calls:
                messages.append(LLMMessage(role="assistant", content=resp.content, tool_calls=resp.tool_calls))
                for tc in resp.tool_calls:
                    self._confirm_if_dangerous(tc.name, tc.arguments)
                    r = self.tools.call(tc.name, tc.arguments)
                    self.obs.tool_called(tc.name, r.ok, r.error or "")
                    result.trajectory.append({"action": f"tool:{tc.name}", "detail": tc.arguments, "outcome": r.ok})
                    messages.append(LLMMessage(role="tool", name=tc.name, tool_call_id=tc.id, content=r.output or r.error or ""))
                continue

            result.success = True
            result.answer = resp.content
            result.used_skills = [s.name for s in skills]
            result.token_usage = budget.used
            messages.append(LLMMessage(role="assistant", content=resp.content))
            self._session_histories[sid] = messages
            self.storage.store_session(sid, summary=resp.content[:200], token_usage=budget.used)
            self.storage.log_trajectory(
                tid=f"traj:{uuid4().hex[:10]}", session_id=sid, outcome=True,
                used_skills=result.used_skills,
                data={"task": task, "trajectory": result.trajectory, "answer": resp.content},
            )
            if self.config.auto_evolve and len(result.trajectory) >= 3:
                tool_actions = {t.get("action", "") for t in result.trajectory if t.get("action")}
                if len(tool_actions) >= 2:
                    steps = [t["detail"].get("query") or t["action"] for t in result.trajectory]
                    rec = propose_skill(task, [str(s) for s in steps], self.settings.skills_dir, llm=self.router.primary, registry=self.registry)
                    self.registry.register(rec)
                    result.candidate_skill = rec.name
                    self.obs.emit("skill_proposed", skill=rec.name)
            return result

        result.error = "max iterations reached without a final answer"
        return result

    def _run_internal_streaming(self, task: str, sid: str) -> Iterator[LLMResponse]:
        """Streaming variant: yields token chunks as they arrive."""
        self.obs.emit("session_start", session=sid, task=task[:200])
        self.storage.index_memory(sid, task)
        try:
            skills = select_skills(self.registry, task)
        except Exception:
            skills = []
        for s in skills:
            self.obs.skill_activated(s.name)

        system_content = self._build_system(skills)
        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=system_content),
            LLMMessage(role="user", content=task),
        ]

        budget = ContextBudget(max_tokens=self.settings.max_session_tokens)
        tool_schemas = self.tools.schemas()
        full_content = ""

        for step in range(self.config.max_iterations):
            if budget.over_soft:
                messages = self._compact_messages(messages, keep_tokens=self.settings.max_session_tokens // 4)
            try:
                for chunk in self.router.primary.chat_stream(messages, tools=tool_schemas or None):
                    if chunk.content:
                        full_content += chunk.content
                        yield chunk
                    if chunk.has_tool_calls:
                        # collect tool calls for execution
                        pass
            except CtxOverflowError:
                messages = self._compact_messages(messages, keep_tokens=self.settings.max_session_tokens // 4)
                continue
            except Exception as e:
                self.obs.error(classify(e), str(e))
                yield LLMResponse(content=f"Error: [{classify(e)}] {e}")
                return

            budget.reserve(_est(full_content))
            # If no tool calls, we're done
            break

        if full_content:
            messages.append(LLMMessage(role="assistant", content=full_content))
            self._session_histories[sid] = messages
            self.storage.store_session(sid, summary=full_content[:200], token_usage=budget.used)

    def clear_session(self, session_id: str) -> None:
        self._session_histories.pop(session_id, None)

    def get_session_history(self, session_id: str) -> list[LLMMessage]:
        return list(self._session_histories.get(session_id, []))
