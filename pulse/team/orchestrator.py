"""Multi-agent team orchestration.

Implements the agent-team-orchestration pattern:
- **Orchestrator** routes work, tracks state, makes priority calls
- **Builder** produces artifacts
- **Reviewer** checks quality, pushes back on gaps

Workflow: decompose → build (parallel) → review → refine (if needed) → ship.
Each handoff follows the protocol: what done, where, how to verify, issues, next.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pulse.llm.provider import LLMMessage, LLMProvider
from pulse.llm.router import Router
from pulse.orchestrator.subagent import (
    RecursionContext,
    SubagentPool,
    SubagentTask,
    SubagentResult,
    decompose,
    merge_results,
)
from pulse.tools.registry import ToolRegistry

BUILDER_SYSTEM = (
    "You are a Builder agent. Produce a complete, well-structured output for the task. "
    "Be thorough. Include examples when helpful. Do NOT ask questions — deliver."
)

REVIEWER_SYSTEM = (
    "You are a Reviewer agent. Evaluate the builder's output against the original task. "
    "Check: completeness, correctness, clarity, actionability. "
    "If the output is satisfactory, reply with 'APPROVED' on the first line, "
    "then a brief summary of strengths. "
    "If gaps exist, reply with 'RETURNED' on the first line, then list specific "
    "feedback the builder should address. Be precise."
)


@dataclass
class TeamResult:
    """Final result of a team orchestration run: answer, rounds executed and builder outputs."""

    task: str
    success: bool
    answer: str = ""
    rounds: int = 0
    reviewer_notes: str = ""
    builder_results: list[SubagentResult] = field(default_factory=list)
    error: Optional[str] = None


class TeamOrchestrator:
    """Coordinate a Builder → Reviewer → (refine →) Ship pipeline."""

    def __init__(self, max_rounds: int = 2, max_workers: int = 3):
        self.max_rounds = max_rounds
        self.pool = SubagentPool(max_workers=max_workers)

    def run(
        self,
        task: str,
        primary: LLMProvider,
        tools: Optional[ToolRegistry] = None,
        router: Optional[Router] = None,
    ) -> TeamResult:
        """Run the full Builder → Reviewer pipeline for ``task``.

        If ``router`` is provided, sub-agents run in recursive mode with full
        recovery and budget support. Otherwise they use the legacy tool loop.
        """
        try:
            return self._run(task, primary, tools, router)
        except Exception as e:  # noqa: BLE001
            return TeamResult(task=task, success=False, error=str(e))

    def _run(
        self,
        task: str,
        primary: LLMProvider,
        tools: ToolRegistry | None,
        router: Router | None,
    ) -> TeamResult:
        subs = decompose(task, llm=primary)
        feedback = ""
        recursion = (
            RecursionContext(router=router, tools=tools, max_iterations=5)
            if router and tools
            else None
        )
        for round_n in range(1, self.max_rounds + 1):
            ctx = f"(the reviewer returned feedback: {feedback})" if feedback else ""
            sub_tasks = [
                SubagentTask(id=f"b_{i}", description=s, role="builder", context=ctx)
                for i, s in enumerate(subs)
            ]
            builder_results: list[SubagentResult] = self.pool.run(
                sub_tasks,
                primary,
                tools,
                recursive=recursion,
            )
            if not builder_results:
                break
            builder_output = "\n\n---\n\n".join(
                f"[{r.task_id}] {'✓' if r.success else '✗'} {r.answer or r.error}"
                for r in builder_results
            )
            review_resp = primary.chat(
                [
                    LLMMessage(role="system", content=REVIEWER_SYSTEM),
                    LLMMessage(
                        role="user",
                        content=f"ORIGINAL TASK: {task}\n\nBUILDER OUTPUT:\n{builder_output[:3000]}",
                    ),
                ]
            )
            review = review_resp.content.strip()
            if review.upper().startswith("APPROVED"):
                merged = merge_results(task, builder_results, llm=primary)
                return TeamResult(
                    task=task,
                    success=True,
                    answer=merged,
                    rounds=round_n,
                    reviewer_notes=review,
                    builder_results=builder_results,
                )
            feedback = review
        merged = merge_results(task, builder_results, llm=primary)
        return TeamResult(
            task=task,
            success=False,
            answer=merged,
            rounds=self.max_rounds,
            reviewer_notes=f"[max rounds reached] {feedback}",
            builder_results=builder_results,
        )
