"""RL training stubs: reward shaping, training loops, model export.

Pluggable backend:
- Local: simple policy gradient with numpy/scikit-learn
- Remote: call external RL service / OpenAI fine-tuning API
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from pulse.net import safe_parse_json

logger = logging.getLogger(__name__)


@dataclass
class RewardSample:
    session_id: str
    prompt: str
    response: str
    reward: float = 0.0
    metadata: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


class RLTrainer:
    """Minimal RL training loop stub.

    Collects reward samples from trajectories, normalizes rewards, and
    exports datasets for external trainers (OpenAI fine-tuning, TRL, etc.).
    """

    def __init__(self, storage: Any, out_dir: Optional[Path] = None) -> None:
        self.storage = storage
        self.out_dir = Path(out_dir or Path.home() / ".pulse" / "rl")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._buffer: list[RewardSample] = []

    def add_sample(self, sample: RewardSample) -> None:
        self._buffer.append(sample)

    def flush(self) -> Path:
        if not self._buffer:
            return self.out_dir / "empty.jsonl"
        path = self.out_dir / f"rl_{int(time.time())}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for s in self._buffer:
                f.write(
                    json.dumps(
                        {
                            "session_id": s.session_id,
                            "prompt": s.prompt,
                            "response": s.response,
                            "reward": s.reward,
                            "metadata": s.metadata,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        count = len(self._buffer)
        self._buffer.clear()
        logger.info("[rl] flushed %d samples to %s", count, path)
        return path

    def train_step(self) -> dict[str, Any]:
        """Placeholder train step. Returns metrics dict."""
        if not self._buffer:
            return {"status": "no_data"}
        # TODO: implement policy gradient / reward model update
        return {"status": "stub", "samples": len(self._buffer)}


def compute_reward(trajectory: dict[str, Any]) -> float:
    """Heuristic reward from a trajectory row."""
    if not trajectory:
        return 0.0
    outcome = bool(trajectory.get("outcome"))
    used_skills = trajectory.get("used_skills", [])
    if isinstance(used_skills, str):
        used_skills = (
            safe_parse_json(used_skills) if isinstance(used_skills, str) else []
        )
    reward = 1.0 if outcome else -0.2
    reward += 0.1 * min(len(used_skills), 3)
    return float(max(-1.0, min(1.0, reward)))


def backfill_rewards(storage: Any, limit: int = 500) -> int:
    """Recompute rewards for recent trajectories and write RL samples."""
    rows = storage.query_trajectories(limit=limit)
    trainer = RLTrainer(storage)
    for row in rows:
        reward = compute_reward(row)
        data = safe_parse_json(row.get("data"))
        trainer.add_sample(
            RewardSample(
                session_id=row.get("session_id", ""),
                prompt=data.get("task", ""),
                response=data.get("answer", ""),
                reward=reward,
                metadata={
                    "outcome": bool(row.get("outcome")),
                    "used_skills": row.get("used_skills", []),
                },
            )
        )
    path = trainer.flush()
    return sum(1 for _ in path.open("r", encoding="utf-8"))
