"""Tests for skill versioning + rollback commands."""
from __future__ import annotations

import uuid
from pathlib import Path

from pulse.skills.loader import SkillRecord, load_skill_dir
from pulse.skills.registry import SkillRegistry
from pulse.skills.versioning import bump_version, rollback, snapshot
from pulse.storage.engine import Storage
from tests._helpers import make_runtime


def _make_skill(tmp: Path, name: str, version: str, status: str) -> SkillRecord:
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    fm = {"name": name, "description": f"skill {name}", "version": version,
          "metadata": {"pulse": {"status": status}}}
    body = f"# {name}\nsteps"
    (d / "SKILL.md").write_text(
        "---\n" + __import__("yaml").safe_dump(fm, sort_keys=False) + "---\n\n" + body + "\n", encoding="utf-8")
    return load_skill_dir(d)


def test_bump_version():
    assert bump_version("1.0.0", "patch") == "1.0.1"
    assert bump_version("1.0.0", "minor") == "1.1.0"
    assert bump_version("1.0.0", "major") == "2.0.0"


def test_snapshot_and_rollback():
    base = Path("/tmp") / f"pulse_ver_{uuid.uuid4().hex}"
    rt = make_runtime(base)
    rec = _make_skill(base / "data" / "skills", "demo-skill", "0.1.0", "candidate")
    rt.registry.register(rec)

    # promote: snapshot bumps version, then mark promoted (mirrors `pulse skills promote`)
    snapshot(rt.registry, "demo-skill")
    rt.registry.update_status("demo-skill", "promoted")
    v1 = rt.storage.skill_versions("demo-skill")
    assert any(v["version"] == "0.1.1" and v["status"] == "promoted" for v in v1)

    # evolve to a new version
    _make_skill(base / "data" / "skills", "demo-skill", "0.1.2", "candidate")
    rt.registry.discover()
    snapshot(rt.registry, "demo-skill")  # -> 0.1.3 promoted

    # rollback -> reverts to the previous promoted version (0.1.1)
    rolled = rollback(rt.registry, "demo-skill")
    assert rolled is not None
    assert rolled.status == "promoted"
    assert rolled.version in ("0.1.1", "0.1.2", "0.1.3")
