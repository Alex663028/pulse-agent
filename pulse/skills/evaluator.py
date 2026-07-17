"""Evaluated skill self-evolution loop.

This is the fix for Hermes' biggest unverified claim: that auto-generated
skills are actually better. Pulse never promotes a self-evolved skill blindly.
Instead:

  1. A candidate skill is *replayed* against a golden task set in a sandbox.
  2. We measure success_rate / token_cost / steps and compare to the baseline.
  3. A decision is made and the skill moves through a state machine:

        candidate --pass--> promoted --regress--> quarantined
            |                   |                      |
            +--fail--> deprecated <--rollback-- promoted

Promotion, quarantine and rollback are all explicit and reversible.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Callable, Optional

from pulse.skills.loader import SkillRecord
from pulse.skills.registry import SkillRegistry
from pulse.skills.states import DECISION_TO_STATUS

EvalDecision = str  # "promote" | "quarantine" | "rollback" | "deprecate" | "refine"


@dataclass
class RunOutcome:
    """Outcome of a single golden-task run: success flag, token and step cost."""

    success: bool
    tokens: int = 0
    steps: int = 0


@dataclass
class EvalResult:
    """Aggregated metrics and decision for a candidate skill across golden tasks."""

    skill_name: str
    runs: int
    success_rate: float
    avg_tokens: float
    avg_steps: float
    baseline_success_rate: Optional[float]
    delta_success: Optional[float]
    decision: EvalDecision
    reason: str
    metrics: dict = field(default_factory=dict)


# A runner executes one task with a given skill and reports the outcome.
Runner = Callable[[SkillRecord, str], RunOutcome]

# Default acceptance thresholds (tunable).
MIN_SUCCESS_RATE = 0.6
REGRESSION_DELTA = 0.15  # success drop vs baseline that triggers rollback/quarantine


class SkillEvaluator:
    """Evaluates candidate skills against golden tasks and produces a reversible decision."""

    def __init__(self, registry: SkillRegistry, min_success_rate: float = MIN_SUCCESS_RATE):
        self.registry = registry
        self.min_success_rate = min_success_rate

    def evaluate(
        self,
        candidate: SkillRecord,
        runner: Runner,
        golden_tasks: list[str],
        baseline: Optional[SkillRecord] = None,
    ) -> EvalResult:
        """Run ``candidate`` against each golden task via ``runner`` and produce an EvalResult, optionally comparing to ``baseline``."""
        outcomes = [runner(candidate, t) for t in golden_tasks]
        success = [o.success for o in outcomes]
        sr = sum(success) / len(success) if success else 0.0
        avg_tok = statistics.mean([o.tokens for o in outcomes]) if outcomes else 0.0
        avg_steps = statistics.mean([o.steps for o in outcomes]) if outcomes else 0.0

        base_sr = None
        delta = None
        if baseline is not None:
            base_res = self.registry.storage.latest_eval(f"{baseline.name}@{baseline.version}")
            if base_res:
                base_sr = base_res["metrics"].get("success_rate")
                delta = sr - base_sr if base_sr is not None else None

        decision, reason = self._decide(sr, base_sr, candidate)
        return EvalResult(
            skill_name=candidate.name,
            runs=len(outcomes),
            success_rate=sr,
            avg_tokens=avg_tok,
            avg_steps=avg_steps,
            baseline_success_rate=base_sr,
            delta_success=delta,
            decision=decision,
            reason=reason,
            metrics={"success_rate": sr, "avg_tokens": avg_tok, "avg_steps": avg_steps, "runs": len(outcomes)},
        )

    def _decide(self, sr: float, base_sr: Optional[float], candidate: SkillRecord) -> tuple[EvalDecision, str]:
        if sr < self.min_success_rate:
            return "deprecate", f"success_rate {sr:.2f} < min {self.min_success_rate}"
        if base_sr is not None:
            if sr < base_sr - REGRESSION_DELTA:
                # regressed vs a known-good baseline -> roll back to it
                return "rollback", f"regressed vs baseline ({sr:.2f} < {base_sr:.2f})"
            if sr >= base_sr:
                return "promote", f"meets/exceeds baseline ({sr:.2f} >= {base_sr:.2f})"
            # slightly below baseline but above min -> refine, keep candidate
            return "refine", f"below baseline but acceptable ({sr:.2f})"
        # No baseline: accept if it clears the bar.
        return "promote", f"clears min success_rate ({sr:.2f})"

    def apply(self, result: EvalResult, candidate: SkillRecord, baseline: Optional[SkillRecord] = None) -> None:
        """Persist the decision: update status + record the eval run.

        For rollback decisions, also invokes the versioning.rollback() path
        to restore the baseline's known-good SKILL.md content durably.
        """
        new_status = DECISION_TO_STATUS.get(result.decision, "candidate")

        # Rollback: restore the baseline/known-good version durably
        if result.decision == "rollback":
            from pulse.skills.versioning import rollback
            target_version = baseline.version if baseline else None
            rollback(self.registry, candidate.name, to_version=target_version)
            new_status = "promoted"

        self.registry.update_status(candidate.name, new_status, metrics=result.metrics)
        self.registry.storage.record_eval(
            run_id=f"{candidate.name}-{int(__import__('time').time())}",
            skill_id=f"{candidate.name}@{candidate.version}",
            baseline_id=f"{baseline.name}@{baseline.version}" if baseline else None,
            decision=result.decision,
            metrics=result.metrics,
        )
