"""Skill evolution: distill a successful trajectory into a candidate skill.

Fix for "skills self-improve but quality is unverified": Pulse only *proposes*
a candidate (status=candidate). It is then evaluated (see evaluator.py) before
any promotion. Draft generation uses a template; an optional LLM pass refines
the prose (darwin-skill style iterative polish).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from pulse.llm.provider import LLMMessage, LLMProvider
from pulse.skills.loader import SkillRecord, dump_skill_md, load_skill_dir

_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _slug(task: str, max_words: int = 4) -> str:
    words = re.findall(r"[a-z0-9]+", task.lower())
    slug = "-".join(words[:max_words])
    if not _NAME_RE.match(slug):
        slug = re.sub(r"[^a-z0-9\-]", "-", slug)
        slug = re.sub(r"-+", "-", slug).strip("-") or "task-skill"
    return slug[:48]


def propose_skill(
    task: str,
    steps: list[str],
    skills_dir: Path,
    llm: Optional[LLMProvider] = None,
) -> SkillRecord:
    name = _slug(task)
    skills_dir = Path(skills_dir)
    dest = skills_dir / name
    dest.mkdir(parents=True, exist_ok=True)

    body_steps = "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps)) or "1. (no steps captured)"
    description = f"Auto-distilled skill for: {task[:200]}. Use when a similar multi-step task appears."
    body = (
        f"# How to: {task.strip()}\n\n"
        f"Distilled from a successful run.\n\n"
        f"## Steps\n{body_steps}\n"
    )

    if llm is not None:
        try:
            resp = llm.chat(
                [
                    LLMMessage(role="system", content="Rewrite the following draft skill into a clear, reusable procedure. Keep it concise."),
                    LLMMessage(role="user", content=body),
                ]
            )
            if resp.content:
                body = resp.content
        except Exception:
            pass

    fm = {
        "name": name,
        "title": task.strip()[:80] or name,
        "description": description,
        "version": "0.1.0",
        "metadata": {"pulse": {"source": "self_evolved", "status": "candidate"}},
    }
    (dest / "SKILL.md").write_text(dump_skill_md(SkillRecord(id=f"{name}@0.1.0", name=name, path=dest, version="0.1.0", frontmatter=fm, body=body, status="candidate")), encoding="utf-8")
    return load_skill_dir(dest)
