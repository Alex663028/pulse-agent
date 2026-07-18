"""Skills Hub integration: install skills from the ecosystem.

Supports installing from a local directory (path) or a git repository URL.
This is how Pulse reuses the existing agentskills.io / Hermes skill ecosystem
without forking it.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from pulse.config.settings import Settings
from pulse.skills.registry import SkillRegistry


def install_skill(registry: SkillRegistry, location: str, settings: Settings) -> str:
    """Install a skill from ``location`` (path or git URL). Returns the skill name."""
    src = Path(location)
    if src.exists() and src.is_dir():
        skill_dir = src
    else:
        # treat as a git URL
        parsed = urlparse(location)
        if parsed.scheme in ("http", "https", "git", "ssh") or location.endswith(
            ".git"
        ):
            with tempfile.TemporaryDirectory() as tmp:
                subprocess.run(
                    ["git", "clone", "--depth", "1", location, tmp + "/repo"],
                    check=True,
                    capture_output=True,
                )
                # find the skill dir (one containing SKILL.md) at repo root or one level down
                skill_dir = _find_skill_dir(Path(tmp) / "repo")
                if not skill_dir:
                    raise FileNotFoundError(
                        f"no SKILL.md found in cloned repo {location}"
                    )
                dest_name = skill_dir.name
                dest = settings.skills_dir / dest_name
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(skill_dir, dest)
                registry.discover()
                return dest_name
        raise ValueError(f"cannot resolve skill location: {location}")

    # local path install
    dest = settings.skills_dir / src.name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    registry.discover()
    rec = registry.get(src.name)
    return rec.name if rec else src.name


def _find_skill_dir(root: Path) -> Path | None:
    if (root / "SKILL.md").exists():
        return root
    for child in root.iterdir():
        if child.is_dir() and (child / "SKILL.md").exists():
            return child
    return None
