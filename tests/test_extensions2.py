"""Tests for RAG vector backends and RL training stubs."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from pulse.rag.vector import ChromaVectorStore, QdrantVectorStore, SQLiteVectorStore
from pulse.rl.train import RewardSample, RLTrainer, backfill_rewards, compute_reward
from tests._helpers import make_runtime


class TestSQLiteVectorStore:
    def test_upsert_and_search(self, tmp_path):
        from pulse.storage.engine import Storage

        db = tmp_path / "pulse.db"
        storage = Storage(db)
        store = SQLiteVectorStore(storage)
        store.upsert("doc1", "hello world")
        hits = store.search("hello", limit=1)
        assert len(hits) == 1
        assert hits[0].doc_id == "doc1"


class TestChromaVectorStore:
    def test_upsert_and_search(self):
        col = MagicMock()
        col.query.return_value = {"documents": [["hello"]], "ids": [["d1"]], "distances": [[0.1]]}
        store = ChromaVectorStore(col)
        store.upsert("d1", "hello")
        hits = store.search("hello", limit=1)
        assert hits[0].doc_id == "d1"
        assert hits[0].score == pytest.approx(0.9)

    def test_search_failure_returns_empty(self):
        col = MagicMock()
        col.query.side_effect = RuntimeError("boom")
        store = ChromaVectorStore(col)
        assert store.search("q", limit=1) == []


class TestQdrantVectorStore:
    def test_upsert_and_search(self):
        client = MagicMock()
        client.search.return_value = [MagicMock(id="d1", payload={"text": "hello"}, score=0.8)]
        store = QdrantVectorStore(client, collection="c")
        store.upsert("d1", "hello")
        hits = store.search("q", limit=1)
        assert hits[0].doc_id == "d1"

    def test_search_failure_returns_empty(self):
        client = MagicMock()
        client.search.side_effect = RuntimeError("boom")
        store = QdrantVectorStore(client)
        assert store.search("q", limit=1) == []


class TestComputeReward:
    def test_success_positive(self):
        traj = {"outcome": True, "used_skills": ["search", "calc"]}
        assert compute_reward(traj) == pytest.approx(1.0)

    def test_failure_negative(self):
        traj = {"outcome": False, "used_skills": []}
        assert compute_reward(traj) == pytest.approx(-0.2)

    def test_string_used_skills(self):
        traj = {"outcome": True, "used_skills": '["a","b","c"]'}
        assert compute_reward(traj) == pytest.approx(1.0)

    def test_clamp_range(self):
        traj = {"outcome": True, "used_skills": ["a", "b", "c", "d"]}
        r = compute_reward(traj)
        assert -1.0 <= r <= 1.0


class TestRLTrainer:
    def test_add_and_flush(self, tmp_path):
        storage = MagicMock()
        trainer = RLTrainer(storage, out_dir=tmp_path)
        trainer.add_sample(RewardSample(session_id="s1", prompt="p", response="r", reward=1.0))
        path = trainer.flush()
        assert path.exists()
        with path.open("r", encoding="utf-8") as f:
            line = f.readline()
        assert json.loads(line)["reward"] == 1.0

    def test_flush_empty_returns_path(self, tmp_path):
        storage = MagicMock()
        trainer = RLTrainer(storage, out_dir=tmp_path)
        path = trainer.flush()
        assert "empty" in str(path.name)

    def test_train_step_no_data(self, tmp_path):
        storage = MagicMock()
        trainer = RLTrainer(storage, out_dir=tmp_path)
        assert trainer.train_step() == {"status": "no_data"}


class TestBackfillRewards:
    def test_backfill_count(self, tmp_path):
        rt = make_runtime(tmp_path)
        rt.storage.log_trajectory(
            tid="t1", session_id="s1", outcome=True, used_skills=["search"],
            data={"task": "q", "answer": "a"},
        )
        count = backfill_rewards(rt.storage, limit=10)
        assert count == 1


class TestObservabilityExt:
    def test_emit_records_trace_when_ext_attached(self):
        from pulse.orchestrator.observability import Observability

        obs = Observability(trace_id="tid")
        ts = MagicMock()
        ext = MagicMock()
        ext.trace_store = ts
        ext.langsmith = None
        ext.langfuse = None
        obs._ext = ext
        obs._log.debug = MagicMock()
        obs.emit("tool_called", tool="x", ok=True)
        assert ts.record.called
        recorded = ts.record.call_args[0][0]
        assert recorded.trace_id == "tid"
        assert recorded.name == "tool_called"
