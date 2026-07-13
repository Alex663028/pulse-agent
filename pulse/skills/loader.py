"""Skill loader — compatible with the agentskills.io open standard AND Hermes'
extended frontmatter.

agentskills.io requires ``name`` (lowercase-hyphen, == directory name) and
``description``. Hermes additionally uses ``title/version/author/dependencies/
platforms/metadata.hermes``. Our loader *tolerates and preserves* every extra
field so existing ecosystem skills load without error.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import yaml

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)

SkillSource = Literal["bundled", "hub", "self_evolved"]
SkillStatus = Literal["candidate", "promoted", "quarantined", "deprecated"]


@dataclass
class SkillRecord:
    id: str
    name: str
    path: Path
    version: str = "0.0.0"
    source: SkillSource = "bundled"
    frontmatter: dict = field(default_factory=dict)
    body: str = ""
    status: SkillStatus = "candidate"
    metrics: dict = field(default_factory=dict)

    @property
    def description(self) -> str:
        return self.frontmatter.get("description", "")

    @property
    def title(self) -> str:
        return self.frontmatter.get("title", self.name)

    @property
    def keywords(self) -> list[str]:
        desc = self.description.lower()
        # name tokens + salient words from description
        toks = set(self.name.split("-"))
        for w in re.findall(r"[a-z]{4,}", desc):
            toks.add(w)
        return sorted(toks)


def parse_skill_md(text: str) -> tuple[dict, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        # No frontmatter: treat whole file as body with a derived name.
        return {}, text
    fm = yaml.safe_load(m.group(1)) or {}
    if not isinstance(fm, dict):
        fm = {}
    return fm, m.group(2)


def load_skill_dir(path: Path) -> SkillRecord:
    path = Path(path)
    skill_md = path / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"no SKILL.md in {path}")
    fm, body = parse_skill_md(skill_md.read_text(encoding="utf-8"))
    name = fm.get("name") or path.name
    if not NAME_RE.match(name):
        # Preserve but flag; do not silently break on Hermes-style names.
        fm.setdefault("_name_warning", f"name '{name}' not lowercase-hyphen")
    version = str(fm.get("version", "0.0.0"))
    return SkillRecord(
        id=f"{name}@{version}",
        name=name,
        path=path,
        version=version,
        source=fm.get("metadata", {}).get("pulse", {}).get("source", "bundled"),
        frontmatter=fm,
        body=body.strip(),
        status=fm.get("metadata", {}).get("pulse", {}).get("status", "candidate"),
    )


def dump_skill_md(record: SkillRecord) -> str:
    """Serialize a SkillRecord back to agentskills.io-compatible SKILL.md."""
    fm = dict(record.frontmatter)
    fm["name"] = record.name
    fm["description"] = record.description
    fm["version"] = record.version
    # keep pulse metadata in sync
    meta = fm.setdefault("metadata", {})
    pulse = meta.setdefault("pulse", {})
    pulse["status"] = record.status
    header = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{header}\n---\n\n{record.body}\n"
