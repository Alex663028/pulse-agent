"""Skill registry: discover, index, and manage skills across sources.

Sources: bundled starters (shipped with Pulse), user-installed skills
(``~/.pulse/data/skills``), and hub-installed skills. Indexing is progressive:
only name+description are loaded at startup (~100 tokens); the full SKILL.md
body is read on demand.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from pulse.config.settings import Settings
from pulse.skills.loader import SkillRecord, SkillStatus, load_skill_dir
from pulse.skills.states import DECISION_TO_STATUS
from pulse.storage.engine import Storage

BUNDLED_DIR = Path(__file__).resolve().parent / "bundled"


class SkillRegistry:
    """Discover, index and manage skills from bundled + user + hub sources."""

    def __init__(self, settings: Settings, storage: Storage):
        self.settings = settings
        self.storage = storage
        self._index: dict[str, SkillRecord] = {}
        self.discover()

    def discover(self) -> None:
        """Re-scan all skill roots and rebuild the in-memory index, restoring last-known statuses."""
        self._index.clear()
        roots = [BUNDLED_DIR, self.settings.skills_dir]
        for root in roots:
            root = Path(root)
            if not root.exists():
                continue
            for child in sorted(root.iterdir()):
                if child.is_dir() and (child / "SKILL.md").exists():
                    try:
                        rec = load_skill_dir(child)
                    except (OSError, yaml.YAMLError, KeyError):
                        continue
                    last = self.storage.latest_eval(f"{rec.name}@{rec.version}")
                    if last:
                        rec.status = DECISION_TO_STATUS.get(last.get("decision"), rec.status)
                    self._index[rec.name] = rec

    def list(self) -> list[dict]:
        return [
            {"name": r.name, "title": r.title, "description": r.description, "status": r.status, "version": r.version}
            for r in self._index.values()
        ]

    def get(self, name: str) -> Optional[SkillRecord]:
        return self._index.get(name)

    def names(self) -> list[str]:
        return list(self._index.keys())

    def register(self, record: SkillRecord, copy_to_user: bool = True) -> SkillRecord:
        if copy_to_user:
            dest = self.settings.skills_dir / record.name
            if not dest.exists():
                import shutil
                shutil.copytree(record.path, dest)
                record = load_skill_dir(dest)
        self._index[record.name] = record
        return record

    def update_status(self, name: str, status: SkillStatus, metrics: Optional[dict] = None) -> None:
        rec = self._index.get(name)
        if not rec:
            return
        rec.status = status
        if metrics:
            rec.metrics.update(metrics)
        # On promotion, store an immutable content snapshot for durable rollback
        content = None
        if status == "promoted":
            skill_md = rec.path / "SKILL.md"
            if skill_md.exists():
                content = skill_md.read_text(encoding="utf-8")
        self.storage.save_skill_version(
            skill_name=rec.name,
            version=rec.version,
            path=str(rec.path),
            status=status,
            metrics=rec.metrics,
            content_snapshot=content,
        )
