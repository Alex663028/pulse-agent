"""Self-evolution framework: analyzes runtime patterns and proposes improvements.

The agent can:
1. Analyze execution traces to find patterns of failure or inefficiency
2. Propose skill improvements based on accumulated corrections and failures
3. Suggest new tools based on repeated manual workarounds
4. Self-diagnose and propose system prompt refinements

This is the core "self-improving" loop that distinguishes Pulse from vanilla agents.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EvolutionSignal:
    """A signal detected from runtime analysis that may trigger evolution."""
    kind: str  # "repeated_failure", "correction_pattern", "tool_gap", "prompt_drift", "skill_regression"
    source: str  # module/skill/tool that triggered this
    description: str
    evidence: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5  # 0..1, higher = more certain
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "source": self.source,
            "description": self.description,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }


@dataclass
class EvolutionProposal:
    """A concrete proposal for self-improvement."""
    title: str
    description: str
    action: str  # "improve_skill", "add_tool", "refine_prompt", "fix_bug", "add_skill"
    target: str  # name of skill/tool/prompt to change
    diff: str | None = None  # proposed content change (SKILL.md body, tool code, etc.)
    signals: list[EvolutionSignal] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "action": self.action,
            "target": self.target,
            "diff": self.diff,
            "signals": [s.to_dict() for s in self.signals],
            "created_at": self.created_at,
        }


class EvolutionAnalyzer:
    """Analyzes runtime patterns and generates evolution signals.

    This is the core engine for self-improvement. It inspects:
    - Trajectory data (success/failure patterns, tool usage)
    - User corrections (what the user had to correct repeatedly)
    - Tool failures (which tools fail and why)
    - Skill usage (which skills are used vs. which are ignored)
    """

    def __init__(self, storage, registry, curator=None):
        self.storage = storage
        self.registry = registry
        self.curator = curator

    def analyze(self) -> list[EvolutionSignal]:
        """Run full analysis and return detected signals."""
        signals: list[EvolutionSignal] = []
        signals.extend(self._analyze_corrections())
        signals.extend(self._analyze_tool_failures())
        signals.extend(self._analyze_skill_gaps())
        signals.extend(self._analyze_trajectory_patterns())
        return [s for s in signals if s.confidence > 0.3]

    def _analyze_corrections(self) -> list[EvolutionSignal]:
        """Detect patterns in user corrections."""
        signals = []
        trajectories = self.storage.query_trajectories(outcome=False, limit=50)

        tool_failure_counts: dict[str, int] = {}
        for t in trajectories:
            data_str = t.get("data", "{}")
            try:
                data = json.loads(data_str) if isinstance(data_str, str) else {}
            except json.JSONDecodeError:
                data = {}
            for step in data.get("trajectory", []):
                if not step.get("outcome", True):
                    tool = step.get("action", "").replace("tool:", "")
                    if tool:
                        tool_failure_counts[tool] = tool_failure_counts.get(tool, 0) + 1

        for tool, count in tool_failure_counts.items():
            if count >= 3:
                signals.append(EvolutionSignal(
                    kind="repeated_failure",
                    source=f"tool:{tool}",
                    description=f"Tool '{tool}' failed {count} times in recent trajectories",
                    evidence={"tool": tool, "failure_count": count},
                    confidence=min(0.9, 0.3 + count * 0.1),
                ))

        return signals

    def _analyze_tool_failures(self) -> list[EvolutionSignal]:
        """Check if any registered tools have high failure rates."""
        signals = []
        trajectories = self.storage.query_trajectories(limit=200)
        for t in trajectories:
            data_str = t.get("data", "{}")
            try:
                data = json.loads(data_str) if isinstance(data_str, str) else {}
            except json.JSONDecodeError:
                data = {}
            for step in data.get("trajectory", []):
                action = step.get("action", "")
                if not step.get("outcome", True) and action.startswith("tool:"):
                    tool_name = action[5:]
                    signals.append(EvolutionSignal(
                        kind="tool_gap",
                        source=f"tool:{tool_name}",
                        description=f"Tool '{tool_name}' failed: {step.get('detail', 'unknown')}",
                        evidence={"tool": tool_name, "detail": step.get("detail", "")},
                        confidence=0.5,
                    ))
        return signals

    def _analyze_skill_gaps(self) -> list[EvolutionSignal]:
        """Detect tasks that are performed repeatedly without a dedicated skill."""
        signals = []
        trajectories = self.storage.query_trajectories(outcome=True, limit=100)

        task_patterns: dict[str, int] = {}
        for t in trajectories:
            data_str = t.get("data", "{}")
            try:
                data = json.loads(data_str) if isinstance(data_str, str) else {}
            except json.JSONDecodeError:
                data = {}
            task = data.get("task", "")
            if task:
                key = " ".join(task.split()[:3]).lower()
                task_patterns[key] = task_patterns.get(key, 0) + 1

        for pattern, count in task_patterns.items():
            if count >= 5:
                signals.append(EvolutionSignal(
                    kind="skill_gap",
                    source=f"task:{pattern}",
                    description=f"Task pattern '{pattern}' appeared {count} times — candidate for a new skill",
                    evidence={"pattern": pattern, "count": count},
                    confidence=min(0.85, 0.4 + count * 0.05),
                ))

        return signals

    def _analyze_trajectory_patterns(self) -> list[EvolutionSignal]:
        """Look for patterns like excessive tool calls, loops, etc."""
        signals = []
        trajectories = self.storage.query_trajectories(limit=50)

        for t in trajectories:
            data_str = t.get("data", "{}")
            try:
                data = json.loads(data_str) if isinstance(data_str, str) else {}
            except json.JSONDecodeError:
                data = {}
            traj = data.get("trajectory", [])
            if len(traj) > 15:
                signals.append(EvolutionSignal(
                    kind="prompt_drift",
                    source="orchestrator",
                    description=f"Trajectory had {len(traj)} steps — possible prompt inefficiency",
                    evidence={"steps": len(traj), "session": t.get("session_id", "")},
                    confidence=0.4,
                ))

        return signals


class EvolutionEngine:
    """Generates concrete improvement proposals from signals."""

    def __init__(self, analyzer: EvolutionAnalyzer, skills_dir: Path):
        self.analyzer = analyzer
        self.skills_dir = Path(skills_dir)

    def generate_proposals(self) -> list[EvolutionProposal]:
        """Analyze and generate concrete proposals."""
        signals = self.analyzer.analyze()
        proposals: list[EvolutionProposal] = []

        for signal in signals:
            if signal.kind == "repeated_failure":
                proposals.append(self._propose_tool_fix(signal))
            elif signal.kind == "skill_gap":
                proposals.append(self._propose_new_skill(signal))
            elif signal.kind == "correction_pattern":
                proposals.append(self._propose_prompt_refinement(signal))
            elif signal.kind == "tool_gap":
                proposals.append(self._propose_tool_improvement(signal))
            elif signal.kind == "prompt_drift":
                proposals.append(self._propose_prompt_refinement(signal))

        return proposals

    def _propose_tool_fix(self, signal: EvolutionSignal) -> EvolutionProposal:
        tool_name = signal.evidence.get("tool", signal.source.split(":")[-1])
        return EvolutionProposal(
            title=f"Fix repeated failures in tool '{tool_name}'",
            description=signal.description,
            action="fix_bug",
            target=tool_name,
            signals=[signal],
        )

    def _propose_new_skill(self, signal: EvolutionSignal) -> EvolutionProposal:
        pattern = signal.evidence.get("pattern", signal.source.split(":")[-1])
        return EvolutionProposal(
            title=f"Create skill for '{pattern}' tasks",
            description=signal.description,
            action="add_skill",
            target=f"auto-{pattern.replace(' ', '-')}",
            signals=[signal],
        )

    def _propose_prompt_refinement(self, signal: EvolutionSignal) -> EvolutionProposal:
        return EvolutionProposal(
            title=f"Refine prompts based on: {signal.description[:60]}",
            description=signal.description,
            action="refine_prompt",
            target=signal.source,
            signals=[signal],
        )

    def _propose_tool_improvement(self, signal: EvolutionSignal) -> EvolutionProposal:
        tool_name = signal.evidence.get("tool", signal.source.split(":")[-1])
        return EvolutionProposal(
            title=f"Improve tool '{tool_name}'",
            description=signal.description,
            action="improve_skill",
            target=tool_name,
            signals=[signal],
        )

    def apply_proposal(self, proposal: EvolutionProposal) -> dict:
        """Attempt to automatically apply a proposal (non-destructive)."""
        result = {"proposal": proposal.title, "status": "pending"}

        try:
            if proposal.action == "add_skill":
                result.update(self._apply_add_skill(proposal))
            elif proposal.action == "refine_prompt":
                result.update(self._apply_refine_prompt(proposal))
            elif proposal.action == "fix_bug":
                result.update(self._apply_tool_fix(proposal))
            elif proposal.action == "improve_skill":
                result.update(self._apply_improve_skill(proposal))
            else:
                result["status"] = "skipped"
                result["reason"] = f"Unknown action: {proposal.action}"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

        return result

    def _apply_add_skill(self, proposal: EvolutionProposal) -> dict:
        """Create a new skill directory with a draft SKILL.md."""
        skill_name = proposal.target
        skill_dir = self.skills_dir / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)

        evidence = proposal.signals[0].evidence if proposal.signals else {}
        pattern = evidence.get("pattern", skill_name)

        draft = (
            f"# Auto-generated skill: {skill_name}\n\n"
            f"Distilled from repeated task pattern: '{pattern}'\n\n"
            f"## Context\n"
            f"This skill was auto-generated because the agent observed the task pattern\n"
            f"'{pattern}' occurring {evidence.get('count', '?')} times.\n\n"
            f"## Steps\n"
            f"(Fill in the specific steps based on successful trajectories)\n\n"
            f"## Success Criteria\n"
            f"- Task completes in fewer tool calls\n"
            f"- Consistent output quality\n"
        )

        (skill_dir / "SKILL.md").write_text(draft, encoding="utf-8")
        return {"status": "applied", "skill": skill_name, "path": str(skill_dir)}

    def _apply_refine_prompt(self, proposal: EvolutionProposal) -> dict:
        return {
            "status": "queued",
            "reason": "Prompt refinement requires human approval",
            "proposal": proposal.to_dict(),
        }

    def _apply_tool_fix(self, proposal: EvolutionProposal) -> dict:
        return {
            "status": "queued",
            "reason": "Tool code changes require human approval",
            "proposal": proposal.to_dict(),
        }

    def _apply_improve_skill(self, proposal: EvolutionProposal) -> dict:
        return {
            "status": "queued",
            "reason": "Skill content changes require human approval",
            "proposal": proposal.to_dict(),
        }


__all__ = [
    "EvolutionSignal",
    "EvolutionProposal",
    "EvolutionAnalyzer",
    "EvolutionEngine",
]
