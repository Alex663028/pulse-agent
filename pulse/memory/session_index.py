"""Session index: persist each turn's content into the FTS5 memory index so it
is searchable across sessions (a core Hermes feature, done locally here)."""
from __future__ import annotations

from uuid import uuid4

from pulse.storage.engine import Storage


class SessionIndex:
    def __init__(self, storage: Storage):
        self.storage = storage

    def index_turn(self, session_id: str, content: str) -> None:
        content = (content or "").strip()
        if content:
            self.storage.index_memory(session_id or f"sess:{uuid4().hex[:8]}", content)
