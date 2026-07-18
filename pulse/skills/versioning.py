"""Skill versioning & rollback.

Promoted skills are versioned so a regression can be rolled back to a known-good
snapshot. Each promoted version stores an immutable content snapshot in SQLite so
rollback restores both the version metadata and the SKILL.md bytes durably.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from pulse.skills.loader import SkillRecord, dump_skill_md
from pulse.skills.registry import SkillRegistry


def bump_version(version: str, level: str = "patch") -> str:
    """Increment a semver ``version`` string at the given level (``major``/``minor``/``patch``)."""
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", version or "0.0.0")
    maj, min_, pat = (int(x) for x in (m.groups() if m else (0, 0, 0)))
    if level == "major":
        maj, min_, pat = maj + 1, 0, 0
    elif level == "minor":
        min_, pat = min_ + 1, 0
    else:
        pat += 1
    return f"{maj}.{min_}.{pat}"


def _read_skill_md_bytes(path: Path) -> str:
    """Read the raw SKILL.md bytes from a skill path."""
    skill_md = Path(path) / "SKILL.md"
    if skill_md.exists():
        return skill_md.read_text(encoding="utf-8")
    return ""


def snapshot(
    registry: SkillRegistry, name: str, level: str = "patch"
) -> Optional[SkillRecord]:
    """Bump version + persist a new SKILL.md snapshot with immutable content backup."""
    rec = registry.get(name)
    if not rec:
        return None
    new_ver = bump_version(rec.version, level)
    rec.version = new_ver
    rec.frontmatter["version"] = new_ver
    # Write the new SKILL.md
    content = dump_skill_md(rec)
    (rec.path / "SKILL.md").write_text(content, encoding="utf-8")
    # Save with immutable content snapshot
    registry.storage.save_skill_version(
        skill_name=name,
        version=new_ver,
        path=str(rec.path),
        status=rec.status,
        metrics=rec.metrics,
        content_snapshot=content,
    )
    return rec


def rollback(
    registry: SkillRegistry, name: str, to_version: Optional[str] = None
) -> Optional[SkillRecord]:
    """Roll a skill back to a previous version, restoring both metadata and SKILL.md bytes.

    Uses the immutable content_snapshot stored in skill_versions to durably restore
    the prior known-good SKILL.md, so a fresh registry loads the restored body.
    """
    versions = registry.storage.skill_versions(name)
    if not versions:
        return None
    if to_version:
        target = next((v for v in versions if v["version"] == to_version), None)
    else:
        # latest non-current version that was promoted and has a content snapshot
        target = next(
            (
                v
                for v in versions
                if v["version"] != versions[0]["version"]
                and v.get("status") == "promoted"
                and v.get("content_snapshot")
            ),
            # fallback: latest with any snapshot
            next((v for v in versions if v.get("content_snapshot")), versions[-1]),
        )
    if not target:
        return None

    rec = registry.get(name)
    if rec:
        # Restore version and status
        rec.version = target["version"]
        rec.status = "promoted"
        rec.frontmatter["version"] = target["version"]

        # Restore content from immutable snapshot (durable across restarts)
        restored_body = target.get("content_snapshot")
        if restored_body:
            (rec.path / "SKILL.md").write_text(restored_body, encoding="utf-8")
            rec.body = restored_body
            # Re-parse to sync frontmatter
            from pulse.skills.loader import parse_skill_md

            fm, body = parse_skill_md(restored_body)
            if fm:
                rec.frontmatter.update(fm)
        else:
            # No snapshot: read whatever is on disk
            disk_body = _read_skill_md_bytes(rec.path)
            if disk_body:
                rec.body = disk_body

        # Persist as a new version row (so rollback is also versioned)
        registry.storage.save_skill_version(
            skill_name=name,
            version=target["version"],
            path=str(rec.path),
            status="promoted",
            metrics=target.get("metrics", {}),
            content_snapshot=restored_body,
        )
    return rec
