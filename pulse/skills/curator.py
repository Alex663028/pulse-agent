"""Skill curator: background maintenance for agent-created skills.

Tracks usage, marks idle skills stale, archives stale ones, keeps a pre-run
tar.gz backup so nothing is lost. Only touches skills with agent provenance.
"""

from __future__ import annotations

import json
import logging
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SkillUsage:
    """Usage statistics for a single skill."""

    name: str
    use_count: int = 0
    view_count: int = 0
    patch_count: int = 0
    last_activity_at: float = 0.0
    state: str = "candidate"
    pinned: bool = False
    created_at: float = 0.0
    created_by: str = "agent"

    def touch(self) -> None:
        """Record activity."""
        self.last_activity_at = time.time()
        self.use_count += 1

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, data: dict) -> "SkillUsage":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class SkillCurator:
    """Background curator for skill lifecycle management.

    Tracks usage, marks stale skills, archives idle ones.
    Only touches skills with created_by="agent" (not bundled or hub-installed).
    """

    def __init__(
        self, skills_dir: Path, stale_after_days: int = 30, archive_after_days: int = 60
    ) -> None:
        self.skills_dir = Path(skills_dir)
        self.stale_after_days = stale_after_days
        self.archive_after_days = archive_after_days
        self._usage_file = self.skills_dir / ".usage.json"
        self._usage: dict[str, SkillUsage] = {}
        self._backup_dir = self.skills_dir / ".backups"
        self._load_usage()

    def _load_usage(self) -> None:
        """Load usage stats from disk."""
        if self._usage_file.exists():
            try:
                data = json.loads(self._usage_file.read_text(encoding="utf-8"))
                self._usage = {k: SkillUsage.from_dict(v) for k, v in data.items()}
            except (json.JSONDecodeError, KeyError, TypeError):
                self._usage = {}

    def _save_usage(self) -> None:
        """Persist usage stats to disk."""
        if not self._usage:
            return
        self._usage_file.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v.to_dict() for k, v in self._usage.items()}
        self._usage_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def touch(self, name: str, action: str = "use") -> None:
        """Record skill activity."""
        usage = self._usage.setdefault(
            name, SkillUsage(name=name, created_at=time.time())
        )
        if action == "use":
            usage.use_count += 1
            usage.last_activity_at = time.time()
        elif action == "view":
            usage.view_count += 1
            usage.last_activity_at = time.time()
        elif action == "patch":
            usage.patch_count += 1
            usage.last_activity_at = time.time()
        self._save_usage()

    def set_state(self, name: str, state: str) -> None:
        """Update skill state."""
        usage = self._usage.get(name)
        if usage:
            usage.state = state
            self._save_usage()

    def pin(self, name: str) -> None:
        """Pin a skill (exempt from auto-transitions)."""
        usage = self._usage.get(name)
        if usage:
            usage.pinned = True
            self._save_usage()

    def unpin(self, name: str) -> None:
        """Unpin a skill."""
        usage = self._usage.get(name)
        if usage:
            usage.pinned = False
            self._save_usage()

    def get_stats(self, name: Optional[str] = None) -> dict | list[dict]:
        """Get usage stats for one or all skills."""
        if name:
            usage = self._usage.get(name)
            return usage.to_dict() if usage else {}
        return [u.to_dict() for u in self._usage.values()]

    def is_stale(self, name: str) -> bool:
        """Check if a skill is stale (idle for too long)."""
        usage = self._usage.get(name)
        if not usage or usage.pinned:
            return False
        if not usage.last_activity_at:
            return False
        idle_seconds = time.time() - usage.last_activity_at
        return idle_seconds > (self.stale_after_days * 86400)

    def is_archive_candidate(self, name: str) -> bool:
        """Check if a skill should be archived (very idle)."""
        usage = self._usage.get(name)
        if not usage or usage.pinned:
            return False
        if not usage.last_activity_at:
            return False
        idle_seconds = time.time() - usage.last_activity_at
        return idle_seconds > (self.archive_after_days * 86400)

    def create_backup(self, name: str) -> Optional[Path]:
        """Create a tar.gz backup of a skill directory."""
        skill_dir = self.skills_dir / name
        if not skill_dir.exists():
            return None
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        backup_path = self._backup_dir / f"{name}-{ts}.tar.gz"
        with tarfile.open(backup_path, "w:gz") as tf:
            tf.add(skill_dir, arcname=name)
        return backup_path

    def run_maintenance(self, registry=None) -> dict:
        """Run maintenance pass: mark stale, archive old.

        Returns a report of actions taken.
        """
        report = {"stale": [], "archived": [], "backups": []}
        for name, usage in list(self._usage.items()):
            if usage.pinned:
                continue
            if usage.created_by != "agent":
                continue

            if self.is_archive_candidate(name):
                # Backup before archiving
                backup = self.create_backup(name)
                if backup:
                    report["backups"].append(str(backup))
                usage.state = "archived"
                report["archived"].append(name)
                logger.info("[curator] archived stale skill: %s", name)
            elif self.is_stale(name):
                usage.state = "stale"
                report["stale"].append(name)
                logger.info("[curator] marked skill as stale: %s", name)

        self._save_usage()
        return report


__all__ = ["SkillCurator", "SkillUsage"]
