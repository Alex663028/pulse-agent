"""M4 tests: RL trajectory export + dialectic user modeling."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from pulse.memory.dialectic import DialecticEngine
from pulse.rl.export import export_jsonl, export_sharegpt
from tests._helpers import make_runtime


def _seed(storage):
    """Seed the DB with sample trajectories (uses unique path per test)."""
    sid = uuid.uuid4().hex[:8]
    for i in range(3):
        storage.store_session(f"{sid}_sess_{i}", f"summary {i}", 50)
    storage.log_trajectory(f"{sid}_t1", f"{sid}_sess_0", True, ["summarize-text"],
                           {"task": "summarize report", "trajectory": [], "answer": "The report covers Q1 results."})
    storage.log_trajectory(f"{sid}_t2", f"{sid}_sess_1", False, [],
                           {"task": "broken task", "trajectory": [], "answer": ""})
    storage.log_trajectory(f"{sid}_t3", f"{sid}_sess_2", True, ["research-paper-writing"],
                           {"task": "draft abstract", "trajectory": [], "answer": "We present a novel method for..."})
    return sid


def test_export_jsonl_format():
    rt = make_runtime(Path("/tmp") / f"pulse_m4_jl_{uuid.uuid4().hex}")
    _seed(rt.storage)
    out = f"/tmp/pulse_test_export_{uuid.uuid4().hex}.jsonl"
    n = export_jsonl(rt.storage, out)
    assert n == 3
    with open(out) as f:
        lines = f.readlines()
    assert all(json.loads(line).get("messages") for line in lines)
    os.unlink(out)


def test_export_sharegpt_format():
    rt = make_runtime(Path("/tmp") / f"pulse_m4_sg_{uuid.uuid4().hex}")
    _seed(rt.storage)
    out = f"/tmp/pulse_test_export_sg_{uuid.uuid4().hex}.json"
    n = export_sharegpt(rt.storage, out)
    assert n == 3
    with open(out) as f:
        data = json.load(f)
    assert all("conversations" in d for d in data)
    os.unlink(out)


def test_export_filter_by_outcome():
    rt = make_runtime(Path("/tmp") / f"pulse_m4_fo_{uuid.uuid4().hex}")
    _seed(rt.storage)
    out = f"/tmp/pulse_test_filter_{uuid.uuid4().hex}.jsonl"
    n = export_jsonl(rt.storage, out, outcome=True)
    assert n == 2
    os.unlink(out)


def test_export_filter_by_skill():
    rt = make_runtime(Path("/tmp") / f"pulse_m4_fs_{uuid.uuid4().hex}")
    _seed(rt.storage)
    out = f"/tmp/pulse_test_skill_{uuid.uuid4().hex}.jsonl"
    n = export_jsonl(rt.storage, out, skill="summarize")
    assert n == 1
    os.unlink(out)


# ---- dialectic ----
def test_dialectic_reflect_with_mock():
    rt = make_runtime(Path("/tmp") / f"pulse_m4_dr_{uuid.uuid4().hex}")
    rt.storage.store_session("s1", "User asked about async Python frameworks.", 40)
    rt.storage.store_session("s2", "User prefers local Ollama and self-hosted tools.", 50)
    rt.memory.add_user_fact("User is a backend engineer.")
    rt.memory.add_user_fact("User works with Python.")

    eng = DialecticEngine(rt.memory, rt.storage, rt.router.primary)
    result = eng.reflect()
    assert len(result) > 20


def test_dialectic_history_and_rollback():
    rt = make_runtime(Path("/tmp") / f"pulse_m4_dh_{uuid.uuid4().hex}")
    rt.storage.store_session("s1", "User prefers local Ollama.", 40)
    rt.memory.add_user_fact("User is a backend engineer.")

    eng = DialecticEngine(rt.memory, rt.storage, rt.router.primary)
    eng.reflect()
    eng.reflect()

    hist = eng.history()
    assert len(hist) >= 1

    restored = eng.rollback(version=hist[0]["version"])
    assert restored is not None
    assert len(restored) > 0
