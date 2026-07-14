"""Skill triggering: pick relevant skills for a task.

Defaults to a transparent keyword-overlap scorer (no LLM needed, fully
offline). An LLM re-ranker can be plugged in later for fuzzy matching.
"""
from __future__ import annotations

import re
from typing import Optional

from pulse.llm.provider import LLMMessage, LLMProvider
from pulse.skills.loader import SkillRecord
from pulse.skills.registry import SkillRegistry


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9\-]{3,}", text.lower()))


def keyword_select(registry: SkillRegistry, query: str, top_k: int = 3) -> list[tuple[SkillRecord, float]]:
    """Score skills by token overlap with ``query`` and return the top_k as (record, score) pairs."""
    q = _tokens(query)
    scored: list[tuple[SkillRecord, float]] = []
    for rec in registry._index.values():
        if rec.status == "deprecated":
            continue
        keys = set(rec.keywords)
        overlap = len(q & keys)
        if overlap:
            scored.append((rec, overlap))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def select(registry: SkillRegistry, query: str, llm: Optional[LLMProvider] = None, top_k: int = 3) -> list[SkillRecord]:
    """Return up to ``top_k`` skills relevant to ``query``, using keyword overlap then falling back to an LLM pick."""
    ranked = keyword_select(registry, query, top_k=top_k)
    if ranked or not llm:
        return [r for r, _ in ranked]
    # fallback: let the LLM name a skill from the catalog
    catalog = "\n".join(f"- {r.name}: {r.description}" for r in registry._index.values())
    try:
        resp = llm.chat(
            [
                LLMMessage(role="system", content="Given the task and the skill catalog, reply with the single best skill name, or 'none'."),
                LLMMessage(role="user", content=f"TASK: {query}\nCATALOG:\n{catalog}"),
            ]
        )
        name = resp.content.strip().split()[0].strip("`-")
        rec = registry.get(name)
        return [rec] if rec else []
    except (RuntimeError, IndexError, AttributeError):
        return []
