"""Dialectic-lite: self-hosted dialectical user modeling.

A transparent replacement for Hermes' Honcho-based dialectic profiling.
Instead of sending user data to a cloud service, Pulse runs the dialectical
loop locally:

    1. thesis    → review existing USER.md claims
    2. antithesis → find counter-/supporting evidence in recent conversations
    3. synthesis  → refine claims; add/remove; boost low-confidence ones

Every synthesis produces a versioned snapshot (USER.v{n}.md) so the user can
inspect the reasoning trail and roll back at any time.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from pulse.llm.provider import LLMMessage, LLMProvider
from pulse.memory.store import MemoryStore
from pulse.storage.engine import Storage

DIALECTIC_SYSTEM = (
    "You are a dialectical user profiler. Review the user's existing profile "
    "('thesis') and recent conversation summaries ('evidence'). Your job:\n\n"
    "1. For each claim in the profile, note whether recent conversations support "
    "or contradict it.\n"
    "2. Refine or remove claims that are contradicted. Strengthen supported ones.\n"
    "3. Add new claims discovered from the evidence (tools used, workflows, "
    "preferences, domain expertise, recurring concerns).\n"
    "4. Output ONLY the updated USER.md content. Keep the same markdown format "
    "(- bullet list of facts). Do NOT add explanations or preamble.\n\n"
    "Be conservative — only add facts clearly supported by the evidence."
)


class DialecticEngine:
    """Local dialectical user-profile refinement with versioned USER.md snapshots."""

    def __init__(self, memory: MemoryStore, storage: Storage, llm: LLMProvider):
        self.memory = memory
        self.storage = storage
        self.llm = llm
        self._version_dir = memory.settings.memory_dir

    def reflect(self) -> str:
        """Run one dialectical cycle. Returns the new USER.md content."""
        profile = self.memory.read_user()
        sessions = self._recent_sessions(limit=20)
        evidence = "\n\n".join(
            f"[session {s.get('id','?')[:12]}] {s.get('summary','')[:300]}"
            for s in sessions
            if s.get("summary")
        )
        if not evidence:
            return profile  # nothing to reflect on

        try:
            resp = self.llm.chat(
                [
                    LLMMessage(role="system", content=DIALECTIC_SYSTEM),
                    LLMMessage(
                        role="user",
                        content=f"## Current profile (thesis)\n{profile}\n\n"
                        f"## Recent conversations (evidence)\n{evidence}",
                    ),
                ],
                max_tokens=1500,
            )
            new_profile = resp.content.strip()
            if new_profile and len(new_profile) > 20 and new_profile != profile:
                self._commit(profile, new_profile)
                return new_profile
        except (RuntimeError, OSError):
            pass
        return profile

    def _commit(self, old: str, new: str) -> None:
        # snapshot current version
        versions = sorted(
            p for p in self._version_dir.glob("USER.v*.md")
            if re.match(r"USER\.v\d+\.md", p.name)
        )
        n = len(versions) + 1
        (self._version_dir / f"USER.v{n}.md").write_text(old, encoding="utf-8")
        # write updated
        self.memory.user_path.write_text(new, encoding="utf-8")

    def history(self) -> list[dict]:
        """List version snapshots with timestamps."""
        versions = sorted(
            self._version_dir.glob("USER.v*.md"),
            key=lambda p: p.stat().st_mtime,
        )
        return [
            {"version": int(re.search(r"USER\.v(\d+)\.md", v.name).group(1)),
             "path": str(v),
             "size": v.stat().st_size}
            for v in versions
        ]

    def rollback(self, version: Optional[int] = None) -> str | None:
        """Restore a previous version. Default: second-to-last."""
        versions = sorted(
            self._version_dir.glob("USER.v*.md"),
            key=lambda p: p.stat().st_mtime,
        )
        if not versions:
            return None
        target = versions[-1] if version is None else next(
            (v for v in versions if int(re.search(r"USER\.v(\d+)\.md", v.name).group(1)) == version), versions[-1]
        )
        old = self.memory.read_user()
        restored = target.read_text(encoding="utf-8")
        # snapshot current before rolling
        n = len(versions) + 1
        (self._version_dir / f"USER.v{n}.md").write_text(old, encoding="utf-8")
        self.memory.user_path.write_text(restored, encoding="utf-8")
        return restored

    def _recent_sessions(self, limit: int) -> list[dict]:
        rows = self.storage._conn.execute(
            "SELECT id, summary FROM sessions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
