"""Tests for memory: FTS5 cross-session recall + user-profile extraction."""
from __future__ import annotations

from pathlib import Path

from pulse.memory.user_profile import UserProfile
from tests._helpers import make_runtime


def test_fts5_cross_session_recall():
    rt = make_runtime(Path("/tmp/pulse_test_mem"))
    rt.storage.index_memory("s1", "The quarterly report shows revenue grew 12%.")
    rt.storage.index_memory("s2", "Deploy the api gateway behind the load balancer.")
    hits = rt.storage.search_memory("quarterly")
    assert any("quarterly" in h.get("content", "").lower() for h in hits)


def test_memory_store_recall_and_notes():
    rt = make_runtime(Path("/tmp/pulse_test_mem2"))
    rt.memory.add_note("User prefers concise answers.")
    hits = rt.memory.recall("concise")
    assert any("concise" in h.get("content", "").lower() for h in hits)
    assert "User prefers concise answers." in rt.memory.read_memory()


def test_user_profile_extraction():
    rt = make_runtime(Path("/tmp/pulse_test_user"))
    prof = UserProfile(rt.memory)
    facts = prof.ingest("I am a backend engineer and I prefer self-hosted tooling.")
    assert any("backend engineer" in f for f in facts)
    assert any("self-hosted" in f for f in facts)
    assert "backend engineer" in rt.memory.read_user()
