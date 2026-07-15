"""Subagent spawning with parallel execution, isolation, and failure merging.

Adopts the agent-team-orchestration pattern:
- Orchestrator decomposes a complex task into sub-tasks (Builder role)
- Sub-agents execute in parallel with isolated contexts and token budgets
- Single-point failure won't take down siblings
- Results are merged by the orchestrator (Reviewer role) into a coherent answer

Recursive mode: sub-agents can run a full Orchestrator loop (with recovery,
budget, skill selection) for more capable multi-step executions.
"""
from __future__ import annotations

import concurrent.futures
import re
import time
from dataclasses import dataclass
from typing import Optional

from pulse.llm.provider import AnthropicError, LLMError, LLMMessage, LLMProvider, LLMResponse
from pulse.tools.registry import ToolRegistry


@dataclass
class SubagentTask:
    """Specification of a single sub-agent task: id, description, role, budget and injected context."""

    id: str
    description: str
    role: str = "builder"
    timeout: float = 60.0
    max_tokens: int = 4096
    context: str = ""  # extra context injected into sub-agent's system prompt


@dataclass
class SubagentResult:
    """Outcome of a single sub-agent execution: success, answer, token/elapsed cost and optional error."""

    task_id: str
    success: bool
    answer: str = ""
    tokens: int = 0
    elapsed: float = 0.0
    error: Optional[str] = None


@dataclass
class RecursionContext:
    """Controls recursive sub-agent behavior. None = legacy single-shot; set for full loop."""
    router: LLMProvider = None
    tools: ToolRegistry = None
    max_iterations: int = 5


class SubagentPool:
    """Execute sub-tasks in parallel with bounded time/tokens and error isolation.

    Each sub-task gets its own execution context. Results are collected as they
    complete; timeouts and exceptions in one sub-task never affect the others
    (single-point-failure-isolated).
    """

    def __init__(self, max_workers: int = 5):
        self.max_workers = max_workers

    def run(
        self,
        tasks: list[SubagentTask],
        primary: LLMProvider,
        tools: Optional[ToolRegistry] = None,
        recursive: Optional[RecursionContext] = None,
    ) -> list[SubagentResult]:
        """Execute all ``tasks`` in parallel and collect results with timeout/error isolation."""
        results: list[SubagentResult] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {
                ex.submit(self._exec_one, t, primary, tools, recursive): t
                for t in tasks
            }
            for fut in concurrent.futures.as_completed(futures):
                task = futures[fut]
                try:
                    results.append(fut.result(timeout=task.timeout + 5))
                except concurrent.futures.TimeoutError:
                    results.append(SubagentResult(task_id=task.id, success=False, error="timeout"))
                except Exception as e:  # noqa: BLE001
                    results.append(SubagentResult(task_id=task.id, success=False, error=str(e)))
        return results

    @staticmethod
    def _exec_one(
        task: SubagentTask,
        primary: LLMProvider,
        tools: Optional[ToolRegistry],
        recursive: Optional[RecursionContext],
    ) -> SubagentResult:
        """Execute a single sub-agent task.

        If ``recursive`` is provided and has a ``router``, the sub-agent runs
        a full recovery-enabled loop (plan→execute→verify). Otherwise it falls
        back to the original multi-step tool loop.
        """
        t0 = time.time()

        # --- Recursive (full Orchestrator-like) mode ---
        if recursive is not None and recursive.router is not None and recursive.tools is not None:
            return SubagentPool._exec_recursive(
                task, primary, tools, recursive, t0
            )

        # --- Legacy single-shot + tool loop mode ---
        return SubagentPool._exec_legacy(task, primary, tools, t0)

    @staticmethod
    def _exec_recursive(
        task: SubagentTask,
        primary: LLMProvider,
        tools: Optional[ToolRegistry],
        recursive: RecursionContext,
        t0: float,
    ) -> SubagentResult:
        """Run sub-agent with recovery, budget, and multi-step tool calls."""
        system = (
            f"You are a {task.role} sub-agent. Execute this single task precisely.\n"
            f"Do NOT ask questions — produce a complete answer.\n"
            f"If you have tools available, use them. Plan first, execute, verify.\n"
            f"{task.context}\n"
        )
        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=task.description),
        ]
        tool_schemas = recursive.tools.schemas() if recursive.tools else None
        total_tokens = 0
        max_iterations = max(1, recursive.max_iterations)

        try:
            for step in range(max_iterations):
                # Simple retry wrapper for transient errors
                resp: LLMResponse | None = None
                for retry in range(2):
                    try:
                        if recursive.router is not None:
                            resp = recursive.router.chat(
                                messages, tools=tool_schemas or None
                            )
                        else:
                            resp = primary.chat(
                                messages, tools=tool_schemas or None
                            )
                        break
                    except (LLMError, AnthropicError) as e:
                        if retry == 0:
                            time.sleep(0.5)
                            continue
                        raise

                if resp is None:
                    return SubagentResult(
                        task_id=task.id,
                        success=False,
                        error="no response",
                        tokens=total_tokens,
                        elapsed=time.time() - t0,
                    )

                total_tokens += resp.usage.total or 0

                if not resp.has_tool_calls:
                    return SubagentResult(
                        task_id=task.id,
                        success=True,
                        answer=resp.content or "(empty)",
                        tokens=total_tokens,
                        elapsed=time.time() - t0,
                    )

                messages.append(
                    LLMMessage(role="assistant", content=resp.content, tool_calls=resp.tool_calls)
                )
                for tc in resp.tool_calls:
                    tool_result = (
                        recursive.tools.call(tc.name, tc.arguments)
                        if recursive.tools else None
                    )
                    output = (
                        tool_result.output if tool_result and tool_result.ok
                        else (tool_result.error if tool_result else "no tools available")
                    )
                    messages.append(
                        LLMMessage(
                            role="tool",
                            name=tc.name,
                            tool_call_id=tc.id,
                            content=output or "",
                        )
                    )
            # max iterations reached
            return SubagentResult(
                task_id=task.id,
                success=True,
                answer=resp.content or "(max iterations reached)",
                tokens=total_tokens,
                elapsed=time.time() - t0,
            )
        except (RuntimeError, OSError, ValueError, LLMError, AnthropicError) as e:
            return SubagentResult(
                task_id=task.id,
                success=False,
                error=str(e),
                tokens=total_tokens,
                elapsed=time.time() - t0,
            )

    @staticmethod
    def _exec_legacy(
        task: SubagentTask,
        primary: LLMProvider,
        tools: Optional[ToolRegistry],
        t0: float,
    ) -> SubagentResult:
        """Original single-shot + multi-step tool loop (no recovery)."""
        system = (
            f"You are a {task.role} sub-agent. Execute this single task precisely.\n"
            f"Do NOT ask questions — produce a complete answer.\n"
            f"{task.context}\n"
        )
        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=task.description),
        ]
        tool_schemas = tools.schemas() if tools else None
        total_tokens = 0
        max_sub_steps = 3
        try:
            for step in range(max_sub_steps):
                resp: LLMResponse = primary.chat(messages, tools=tool_schemas)
                total_tokens += resp.usage.total or 0
                if not resp.has_tool_calls:
                    return SubagentResult(
                        task_id=task.id,
                        success=True,
                        answer=resp.content or "(empty)",
                        tokens=total_tokens,
                        elapsed=time.time() - t0,
                    )
                messages.append(
                    LLMMessage(role="assistant", content=resp.content, tool_calls=resp.tool_calls)
                )
                for tc in resp.tool_calls:
                    tool_result = tools.call(tc.name, tc.arguments) if tools else None
                    output = (
                        tool_result.output if tool_result and tool_result.ok
                        else (tool_result.error if tool_result else "no tools available")
                    )
                    messages.append(
                        LLMMessage(
                            role="tool",
                            name=tc.name,
                            tool_call_id=tc.id,
                            content=output or "",
                        )
                    )
            last_content = resp.content or "(max steps reached)"
            return SubagentResult(
                task_id=task.id,
                success=True,
                answer=last_content,
                tokens=total_tokens,
                elapsed=time.time() - t0,
            )
        except (RuntimeError, OSError, ValueError, LLMError, AnthropicError) as e:
            return SubagentResult(
                task_id=task.id,
                success=False,
                error=str(e),
                tokens=total_tokens,
                elapsed=time.time() - t0,
            )


# ---- decompose: split a complex task into independent sub-tasks ----


def decompose(task: str, llm: Optional[LLMProvider] = None) -> list[str]:
    """Split a complex task into independent sub-tasks. Uses LLM when available, else heuristic."""
    if llm is not None:
        try:
            resp = llm.chat(
                [
                    LLMMessage(
                        role="system",
                        content=(
                            "Decompose the following task into 2-5 independent sub-tasks "
                            "that can be executed in parallel. "
                            "Return each sub-task on its own line, prefixed with '- '."
                        ),
                    ),
                    LLMMessage(role="user", content=task),
                ]
            )
            parts = [ln.strip("- ").strip() for ln in resp.content.split("\n") if ln.strip().startswith("-")]
            if len(parts) >= 2:
                return parts[:5]
        except (RuntimeError, OSError, IndexError, LLMError, AnthropicError):
            pass
    # Heuristic fallback: split on bullet points or numbered items in the original task
    parts = [ln.strip("- ").strip() for ln in task.split("\n") if ln.strip().startswith("-")]
    if len(parts) >= 2:
        return parts[:5]
    # Try numbered list pattern: "1. ... 2. ... 3. ..."
    numbered = re.split(r"\d+\.\s+", task)
    numbered = [p.strip() for p in numbered if p.strip()]
    if len(numbered) >= 2:
        return [f"Step {i+1}: {p}" for i, p in enumerate(numbered)][:5]
    # Try comma/and split: "collect data, analyze trends, and write report"
    for sep in (", and ", ", ", " and ", " then "):
        parts = [p.strip() for p in task.split(sep) if p.strip()]
        if len(parts) >= 2:
            return parts[:5]
    # can't split — single sub-task
    return [task.strip()]


# ---- merge: combine sub-results into a coherent answer ----

MERGE_SYSTEM = (
    "You are a result synthesizer. Combine the following sub-task results into "
    "a single coherent answer for the original task. Preserve all key findings. "
    "Group by topic. Be concise."
)


def merge_results(task: str, results: list[SubagentResult], llm: LLMProvider) -> str:
    """Ask the LLM to merge sub-agent results into one answer."""
    parts = []
    for i, r in enumerate(results):
        tag = "✓" if r.success else "✗"
        parts.append(f"### sub-task {i+1} [{tag}]\n{r.answer or r.error or '(empty)'}")
    merged = "\n\n".join(parts)
    if llm is None or len(merged) < 200:
        return merged
    try:
        resp = llm.chat(
            [
                LLMMessage(role="system", content=MERGE_SYSTEM),
                LLMMessage(role="user", content=f"ORIGINAL: {task}\n\nSUB-RESULTS:\n{merged}"),
            ],
            max_tokens=2000,
        )
        return resp.content or merged
    except (RuntimeError, OSError, LLMError, AnthropicError):
        return merged
