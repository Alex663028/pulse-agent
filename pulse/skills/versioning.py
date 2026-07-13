"""Skill versioning & rollback.

Promoted skills are versioned so a regression can be rolled back to a known-good
snapshot. Version bumps follow semver (patch by default).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from pulse.skills.loader import SkillRecord, dump_skill_md, load_skill_dir
from pulse.skills.registry import SkillRegistry


def bump_version(version: str, level: str = "patch") -> str:
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", version or "0.0.0")
    maj, min_, pat = (int(x) for x in (m.groups() if m else (0, 0, 0)))
    if level == "major":
        maj, min_, pat = maj + 1, 0, 0
    elif level == "minor":
        min_, pat = min_ + 1, 0
    else:
        pat += 1
    return f"{maj}.{min_}.{pat}"


def snapshot(registry: SkillRegistry, name: str, level: str = "patch") -> Optional[SkillRecord]:
    """Bump version + persist a new SKILL.md snapshot (used on promotion)."""
    rec = registry.get(name)
    if not rec:
        return None
    new_ver = bump_version(rec.version, level)
    rec.version = new_ver
    rec.frontmatter["version"] = new_ver
    (rec.path / "SKILL.md").write_text(dump_skill_md(rec), encoding="utf-8")
    registry.storage.save_skill_version(
        skill_name=name, version=new_ver, path=str(rec.path), status=rec.status, metrics=rec.metrics
    )
    return rec


def rollback(registry: SkillRegistry, name: str, to_version: Optional[str] = None) -> Optional[SkillRecord]:
    """Roll a skill back to a previous version (or the latest promoted one)."""
    versions = registry.storage.skill_versions(name)
    if not versions:
        return None
    if to_version:
        target = next((v for v in versions if v["version"] == to_version), None)
    else:
        # latest non-current version that was promoted
        target = next((v for v in versions if v["version"] != versions[0]["version"] and v["status"] == "promoted"), versions[-1])
    if not target:
        return None
    rec = registry.get(name)
    if rec:
        rec.version = target["version"]
        rec.status = "promoted"
        rec.frontmatter["version"] = target["version"]
        registry.storage.save_skill_version(
            skill_name=name, version=target["version"], path=str(rec.path), status="promoted", metrics=target["metrics"]
        )
    return rec
