"""Self-hosted storage: SQLite + FTS5, no external services.

Replaces Hermes' reliance on Honcho/cloud memory backends. Used for session
logs, trajectory capture (for skill evolution + RL export later), eval runs,
skill versioning, and full-text memory search.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    summary TEXT,
    token_usage INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS trajectories (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    outcome INTEGER NOT NULL,
    used_skills TEXT,
    data TEXT
);
CREATE TABLE IF NOT EXISTS eval_runs (
    id TEXT PRIMARY KEY,
    skill_id TEXT NOT NULL,
    baseline_id TEXT,
    created_at TEXT NOT NULL,
    decision TEXT,
    metrics TEXT
);
CREATE TABLE IF NOT EXISTS skill_versions (
    id TEXT PRIMARY KEY,
    skill_name TEXT NOT NULL,
    version TEXT NOT NULL,
    path TEXT,
    status TEXT,
    created_at TEXT NOT NULL,
    metrics TEXT,
    UNIQUE(skill_name, version)
);
CREATE TABLE IF NOT EXISTS fts_memory (
    session_id TEXT,
    content TEXT,
    ts TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS fts_memory_ix USING fts5(content, session_id UNINDEXED, ts UNINDEXED);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    """SQLite-backed storage for sessions, trajectories, evals, skill versions and FTS5 memory.

    Thread-safe: all write operations (sessions, trajectories, memory indexing, skill versions)
    are guarded by a lock so concurrent gateways (TUI + Telegram) can't corrupt the DB.
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._lock = threading.Lock()

    @staticmethod
    def has_fts5() -> bool:
        """Return True if the SQLite build supports the FTS5 full-text extension."""
        try:
            con = sqlite3.connect(":memory:")
            con.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
            return True
        except sqlite3.OperationalError:
            return False

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # ---- sessions & trajectories ----
    def store_session(self, sid: str, summary: Optional[str] = None, token_usage: int = 0) -> None:
        """Insert or replace a session row with its summary and token usage."""
        with self._tx():
            self._conn.execute(
                "INSERT OR REPLACE INTO sessions(id, created_at, summary, token_usage) VALUES(?,?,?,?)",
                (sid, _now(), summary, token_usage),
            )

    def log_trajectory(
        self,
        tid: str,
        session_id: str,
        outcome: bool,
        used_skills: list[str],
        data: dict[str, Any],
    ) -> None:
        """Persist a completed execution trajectory with skills used and outcome flag."""
        with self._tx():
            self._conn.execute(
                "INSERT INTO trajectories(id, session_id, created_at, outcome, used_skills, data) VALUES(?,?,?,?,?,?)",
                (tid, session_id, _now(), int(outcome), json.dumps(used_skills), json.dumps(data)),
            )

    # ---- eval runs ----
    def record_eval(
        self, run_id: str, skill_id: str, baseline_id: Optional[str], decision: str, metrics: dict[str, Any]
    ) -> None:
        """Insert an eval-run row capturing the decision and metrics for a skill."""
        with self._tx():
            self._conn.execute(
                "INSERT INTO eval_runs(id, skill_id, baseline_id, created_at, decision, metrics) VALUES(?,?,?,?,?,?)",
                (run_id, skill_id, baseline_id, _now(), decision, json.dumps(metrics)),
            )

    def latest_eval(self, skill_id: str) -> Optional[dict[str, Any]]:
        """Return the most recent eval row for ``skill_id`` (with parsed metrics), or None."""
        row = self._conn.execute(
            "SELECT * FROM eval_runs WHERE skill_id=? ORDER BY created_at DESC LIMIT 1", (skill_id,)
        ).fetchone()
        if not row:
            return None
        return {**dict(row), "metrics": json.loads(row["metrics"])}

    # ---- skill versions ----
    def save_skill_version(
        self, skill_name: str, version: str, path: Optional[str], status: str, metrics: dict[str, Any]
    ) -> None:
        """Insert or replace a skill_version row keyed by ``skill_name@version``."""
        with self._tx():
            self._conn.execute(
                "INSERT OR REPLACE INTO skill_versions(id, skill_name, version, path, status, created_at, metrics) VALUES(?,?,?,?,?,?,?)",
                (f"{skill_name}@{version}", skill_name, version, path, status, _now(), json.dumps(metrics)),
            )

    def skill_versions(self, skill_name: str) -> list[dict[str, Any]]:
        """Return all stored versions for ``skill_name``, newest first, with parsed metrics."""
        rows = self._conn.execute(
            "SELECT * FROM skill_versions WHERE skill_name=? ORDER BY created_at DESC", (skill_name,)
        ).fetchall()
        return [{**dict(r), "metrics": json.loads(r["metrics"])} for r in rows]

    # ---- trajectory query ----
    def query_trajectories(
        self,
        since: Optional[str] = None,
        outcome: Optional[bool] = None,
        skill: Optional[str] = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Query trajectories filtered by timestamp, outcome and/or skill usage."""
        clauses = []
        params: list[Any] = []
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        if outcome is not None:
            clauses.append("outcome = ?")
            params.append(int(outcome))
        if skill:
            clauses.append("used_skills LIKE ?")
            params.append(f"%{skill}%")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM trajectories {where} ORDER BY created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- memory FTS5 ----
    def index_memory(self, session_id: str, content: str) -> None:
        """Insert a memory blob into both the fallback table and the FTS5 index."""
        with self._tx():
            self._conn.execute(
                "INSERT INTO fts_memory(session_id, content, ts) VALUES(?,?,?)", (session_id, content, _now())
            )
            self._conn.execute(
                "INSERT INTO fts_memory_ix(content, session_id, ts) VALUES(?,?,?)", (content, session_id, _now())
            )

    def search_memory(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Full-text search over indexed memory; falls back to substring scan if FTS5 is unavailable."""
        if not self.has_fts5():
            # graceful degradation: substring scan
            rows = self._conn.execute("SELECT * FROM fts_memory ORDER BY ts DESC").fetchall()
            q = query.lower()
            return [dict(r) for r in rows if q in (r["content"] or "").lower()][:limit]
        rows = self._conn.execute(
            "SELECT * FROM fts_memory_ix WHERE fts_memory_ix MATCH ? ORDER BY ts DESC LIMIT ?",
            (query, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()
