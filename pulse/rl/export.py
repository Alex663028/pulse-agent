"""RL trajectory export.

Convert stored execution trajectories into standard fine-tuning formats:
- ChatML JSONL (OpenAI-compatible)
- ShareGPT JSON (Alpaca-style)

Supports filtering by date, outcome, and skill usage.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from pulse.net import safe_parse_json
from pulse.storage.engine import Storage

SYSTEM_TEMPLATE = (
    "You are Pulse, a reliable self-improving personal assistant. "
    "Follow instructions precisely. Be concise and factual."
)


def _to_chatml(traj: dict[str, Any]) -> dict[str, Any]:
    data = safe_parse_json(traj.get("data"))
    messages = [
        {"role": "system", "content": SYSTEM_TEMPLATE},
        {"role": "user", "content": data.get("task", "")},
    ]
    answer = data.get("answer", "")
    if answer:
        messages.append({"role": "assistant", "content": answer})
    return {
        "messages": messages,
        "metadata": {
            "session_id": traj.get("session_id", ""),
            "outcome": bool(traj.get("outcome")),
            "used_skills": json.loads(traj.get("used_skills", "[]"))
            if isinstance(traj.get("used_skills"), str)
            else traj.get("used_skills", []),
            "created_at": traj.get("created_at", ""),
        },
    }


def _to_sharegpt(traj: dict[str, Any]) -> dict[str, Any]:
    data = safe_parse_json(traj.get("data"))
    task = data.get("task", "")
    answer = data.get("answer", "")
    return {
        "id": traj.get("id", ""),
        "conversations": [
            {"from": "system", "value": SYSTEM_TEMPLATE},
            {"from": "human", "value": task},
            {"from": "gpt", "value": answer},
        ],
    }


def export_jsonl(
    storage: Storage,
    out_path: str,
    *,
    since: Optional[str] = None,
    outcome: Optional[bool] = None,
    skill: Optional[str] = None,
    limit: int = 500,
) -> int:
    """Export trajectories as ChatML JSONL. Returns count of exported records."""
    rows = storage.query_trajectories(
        since=since, outcome=outcome, skill=skill, limit=limit
    )
    count = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(_to_chatml(row), ensure_ascii=False) + "\n")
            count += 1
    return count


def export_sharegpt(
    storage: Storage,
    out_path: str,
    *,
    since: Optional[str] = None,
    outcome: Optional[bool] = None,
    skill: Optional[str] = None,
    limit: int = 500,
) -> int:
    """Export trajectories as ShareGPT JSON array. Returns count."""
    rows = storage.query_trajectories(
        since=since, outcome=outcome, skill=skill, limit=limit
    )
    data = [_to_sharegpt(r) for r in rows]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return len(data)
