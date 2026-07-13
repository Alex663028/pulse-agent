"""Tests for skill loading (agentskills.io + Hermes) and the evaluation loop."""
from __future__ import annotations

from pathlib import Path

import pytest

from pulse.skills.evaluator import RunOutcome, SkillEvaluator
from pulse.skills.loader import SkillRecord, load_skill_dir
from tests._helpers import make_runtime

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_load_hermes_skill_preserves_extensions():
    rec = load_skill_dir(EXAMPLES / "skills" / "research-paper-writing")
    assert rec.name == "research-paper-writing"
    assert rec.frontmatter["version"] == "1.1.0"
    assert rec.frontmatter["author"] == "Orchestra Research"
    # Hermes-specific nested metadata must survive untouched
    assert rec.frontmatter["metadata"]["hermes"]["category"] == "research"
    assert "arxiv" in rec.frontmatter["dependencies"]


def test_load_bundled_agentskills_skill():
    rec = load_skill_dir(Path(__file__).resolve().parent.parent / "pulse" / "skills" / "bundled" / "summarize-text")
    assert rec.name == "summarize-text"
    assert rec.status == "promoted"
    assert "summary" in rec.description.lower()


def _candidate(name="draft-email", version="0.1.0"):
    return SkillRecord(id=f"{name}@{version}", name=name, path=Path("/tmp/x"), version=version, status="candidate")


def test_evaluator_promotes_when_successful():
    rt = make_runtime(Path("/tmp/pulse_test_promote"))
    cand = _candidate()
    rt.registry._index[cand.name] = cand
    ev = SkillEvaluator(rt.registry)
    runner = lambda s, t: RunOutcome(success=True, tokens=100, steps=1)
    res = ev.evaluate(cand, runner, ["task a", "task b", "task c"])
    ev.apply(res, cand)
    assert res.decision == "promote"
    assert rt.registry.get(cand.name).status == "promoted"


def test_evaluator_deprecates_when_poor():
    rt = make_runtime(Path("/tmp/pulse_test_deprecate"))
    cand = _candidate()
    rt.registry._index[cand.name] = cand
    ev = SkillEvaluator(rt.registry)
    runner = lambda s, t: RunOutcome(success=False, tokens=10, steps=1)
    res = ev.evaluate(cand, runner, ["task a", "task b", "task c"])
    assert res.decision in ("deprecate", "quarantine", "refine")
    assert res.success_rate < 0.6


def test_evaluator_rollback_on_regression():
    import uuid

    rt = make_runtime(Path("/tmp") / f"pulse_test_rollback_{uuid.uuid4().hex}")
    base = _candidate(name="base", version="1.0.0")
    rt.registry._index[base.name] = base
    # record a known-good baseline eval
    rt.storage.record_eval("b1", f"{base.name}@{base.version}", None, "promote",
                              {"success_rate": 1.0, "avg_tokens": 80, "avg_steps": 1, "runs": 3})
    cand = _candidate(name="base", version="0.2.0")
    cand.status = "promoted"
    rt.registry._index[cand.name] = cand
    ev = SkillEvaluator(rt.registry)
    # regressed vs baseline but still clears the min bar -> rollback
    runner = lambda s, t: RunOutcome(success=t != "t3", tokens=10, steps=1)
    res = ev.evaluate(cand, runner, ["t1", "t2", "t3"], baseline=base)
    assert res.decision == "rollback"
    assert res.baseline_success_rate == 1.0
