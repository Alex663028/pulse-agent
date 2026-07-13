"""Memory store: Hermes-compatible MEMORY.md + USER.md, indexed for FTS5 search.

This is the self-hosted replacement for Hermes' Honcho-backed memory: notes and
user profile live as plain Markdown files (portable, diffable, private) and are
additionally indexed in local SQLite FTS5 for cross-session recall.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import uuid4

from pulse.config.settings import Settings
from pulse.storage.engine import Storage

DEFAULT_MEMORY = "# MEMORY\n\nAgent notes: environment setup, conventions, and technical discoveries.\n"
DEFAULT_USER = "# USER\n\nUser profile: role, preferences, and recurring workflows.\n"


class MemoryStore:
    def __init__(self, settings: Settings, storage: Storage):
        self.settings = settings
        self.storage = storage
        self.memory_path = settings.memory_dir / "MEMORY.md"
        self.user_path = settings.memory_dir / "USER.md"
        self.ensure()

    def ensure(self) -> None:
        self.settings.memory_dir.mkdir(parents=True, exist_ok=True)
        if not self.memory_path.exists():
            self.memory_path.write_text(DEFAULT_MEMORY, encoding="utf-8")
        if not self.user_path.exists():
            self.user_path.write_text(DEFAULT_USER, encoding="utf-8")

    # ---- notes (MEMORY.md) ----
    def read_memory(self) -> str:
        return self.memory_path.read_text(encoding="utf-8")

    def add_note(self, text: str, index: bool = True) -> None:
        text = text.strip()
        if not text:
            return
        with self.memory_path.open("a", encoding="utf-8") as f:
            f.write(f"\n- {text}\n")
        if index:
            self.storage.index_memory(f"mem:{uuid4().hex[:8]}", text)

    # ---- user profile (USER.md) ----
    def read_user(self) -> str:
        return self.user_path.read_text(encoding="utf-8")

    def add_user_fact(self, fact: str) -> None:
        fact = fact.strip()
        if not fact:
            return
        with self.user_path.open("a", encoding="utf-8") as f:
            f.write(f"\n- {fact}\n")

    # ---- recall ----
    def recall(self, query: str, limit: int = 10) -> list[dict[str, str]]:
        return self.storage.search_memory(query, limit=limit)
