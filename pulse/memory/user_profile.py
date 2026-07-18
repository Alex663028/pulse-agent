"""Lightweight user-profile extraction.

Replaces Hermes' heavier Honcho "dialectic" modeling with a transparent,
self-hosted heuristic: pull explicit self-descriptions from conversation turns
and append them to USER.md. Later milestones can upgrade this to a proper
dialectic-lite model without changing the storage contract.
"""

from __future__ import annotations

import re

from pulse.memory.store import MemoryStore

# Heuristic patterns that signal a stable user fact.
_PATTERNS = [
    r"i am (?:a|an)?\s*([^\.\n]{3,80})",
    r"i'?m (?:a|an)?\s*([^\.\n]{3,80})",
    r"i prefer ([^\.\n]{3,80})",
    r"i like ([^\.\n]{3,80})",
    r"my (?:role|job|team|name) (?:is|is that)\s*([^\.\n]{3,80})",
    r"(?:please|can you) (?:always|default to|use)\s*([^\.\n]{3,80})",
]


def extract_facts(text: str) -> list[str]:
    """Extract stable self-descriptive facts from ``text`` via heuristic patterns; de-duplicates preserving order."""
    facts: list[str] = []
    low = text.lower()
    for pat in _PATTERNS:
        for m in re.finditer(pat, low):
            fact = m.group(1).strip().rstrip(" .")
            if 3 <= len(fact) <= 80:
                facts.append(fact)
    # de-dupe, keep order
    seen, out = set(), []
    for f in facts:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


class UserProfile:
    """Heuristic user-profile manager that ingests facts into USER.md."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def ingest(self, text: str) -> list[str]:
        """Extract facts from ``text`` and append them to USER.md; returns the ingested facts."""
        facts = extract_facts(text)
        for f in facts:
            self.store.add_user_fact(f)
        return facts

    def render(self) -> str:
        """Return the current USER.md contents."""
        return self.store.read_user()
