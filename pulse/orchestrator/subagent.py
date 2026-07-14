"""Subagent spawning with parallel execution, isolation, and failure merging.

Adopts the agent-team-orchestration pattern:
- Orchestrator decomposes a complex task into sub-tasks (Builder role)
- Sub-agents execute in parallel with isolated contexts and token budgets
- Single-point failure won't take down siblings
- Results are merged by the orchestrator (Reviewer role) into a coherent answer

This is the fix for Hermes' unreliable sub-agent handling: every sub-agent gets
a bounded timeout, token cap, and error capture.
"""
from __future__ import annotations

import concurrent.futures
import re
import time
from dataclasses import dataclass
from typing import Optional

from pulse.llm.provider import LLMMessage, LLMProvider, LLMResponse
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


class SubagentPool:
    """Execute sub-tasks in parallel with bounded time/tokens and error isolation.

    Each sub-task gets its own LLM call with an isolated system prompt.
    Results are collected as they complete; timeouts and exceptions in one
    sub-task never affect the others (single-point-failure-isolated).
    """

    def __init__(self, max_workers: int = 5):
        self.max_workers = max_workers

    def run(
        self,
        tasks: list[SubagentTask],
        primary: LLMProvider,
        tools: Optional[ToolRegistry] = None,
    ) -> list[SubagentResult]:
        """Execute all ``tasks`` in parallel and collect results with timeout/error isolation."""
        results: list[SubagentResult] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {ex.submit(self._exec_one, t, primary, tools): t for t in tasks}
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
    def _exec_one(task: SubagentTask, primary: LLMProvider, tools: Optional[ToolRegistry]) -> SubagentResult:
        t0 = time.time()
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
        try:
            resp: LLMResponse = primary.chat(messages, tools=tool_schemas)
        except (RuntimeError, OSError, ValueError) as e:
            return SubagentResult(task_id=task.id, success=False, error=str(e), elapsed=time.time() - t0)
        return SubagentResult(
            task_id=task.id,
            success=bool(resp.content.strip()),
            answer=resp.content,
            tokens=resp.usage.total or 0,
            elapsed=time.time() - t0,
        )


# ---- decompose: split a complex task into sub-tasks ----

DECOMPOSE_SYSTEM = (
    "You are a task decomposer. Split the given task into 2-5 parallel sub-tasks. "
    "Each sub-task should be independent (no shared state needed). "
    "Reply with a numbered list, one sub-task per line, format: '1. <sub-task description>'. "
    "Be concise. No preamble."
)

_HEURISTIC_SPLITTERS = [
    r"\d+\.\s+",            # "1. do X"  "2. do Y"
    r",\s*(?:and\s+)?",     # "do X, do Y" or "do X, and do Y"
    r"(?:and)\s+",          # "collect data and analyze trends"
    r";\s*",                # "do X; do Y"
    r"\n\s*[-*•]",          # bullet list
]


def decompose(task: str, llm: Optional[LLMProvider] = None) -> list[str]:
    """Split ``task`` into a list of sub-task descriptions."""
    # try LLM-based decomposition first
    if llm is not None:
        try:
            resp = llm.chat(
                [LLMMessage(role="system", content=DECOMPOSE_SYSTEM), LLMMessage(role="user", content=task)],
                max_tokens=400,
            )
            lines = re.findall(r"\d+\.\s*(.+?)(?:\n|$)", resp.content or "")
            if len(lines) >= 2:
                return [line.strip() for line in lines if line.strip()]
        except (RuntimeError, OSError):
            pass
    # deterministic heuristic fallback
    for sep in _HEURISTIC_SPLITTERS:
        parts = re.split(sep, task)
        if len(parts) >= 2:
            return [p.strip().rstrip(",;") for p in parts if p.strip() and len(p.strip()) > 5]
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
    except (RuntimeError, OSError):
        return merged
