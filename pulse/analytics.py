"""Usage analytics and insights for the agent."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pulse.config.settings import Settings
from pulse.storage.engine import Storage


@dataclass
class UsageStats:
    """Aggregated usage statistics."""
    total_sessions: int = 0
    total_trajectories: int = 0
    total_tokens: int = 0
    success_count: int = 0
    failure_count: int = 0
    success_rate: float = 0.0
    avg_tokens_per_session: float = 0.0
    skills_used: dict[str, int] = field(default_factory=dict)
    daily_usage: dict[str, dict[str, Any]] = field(default_factory=dict)


class UsageInsights:
    """Compute and report usage statistics."""

    def __init__(self, storage: Storage, settings: Settings) -> None:
        self.storage = storage
        self.settings = settings

    def compute_stats(self, days: int = 30) -> UsageStats:
        """Compute usage statistics for the last N days."""
        stats = UsageStats()
        cutoff = (datetime.now(timezone.utc).timestamp() - days * 86400)

        # Session stats
        sessions = self.storage.list_sessions() if hasattr(self.storage, "list_sessions") else []
        stats.total_sessions = len(sessions)
        for s in sessions:
            stats.total_tokens += s.get("token_usage", 0)

        # Trajectory stats
        trajectories = self.storage.query_trajectories(limit=10000)
        recent = [t for t in trajectories if self._parse_ts(t.get("created_at", "")) > cutoff]
        stats.total_trajectories = len(recent)
        stats.success_count = sum(1 for t in recent if t.get("outcome") == 1)
        stats.failure_count = sum(1 for t in recent if t.get("outcome") == 0)
        total = stats.success_count + stats.failure_count
        stats.success_rate = stats.success_count / total if total else 0.0
        stats.avg_tokens_per_session = (
            stats.total_tokens / stats.total_sessions if stats.total_sessions else 0.0
        )

        # Skills usage
        for t in recent:
            skills_str = t.get("used_skills", "[]")
            try:
                skills = json.loads(skills_str) if isinstance(skills_str, str) else []
                for sk in skills:
                    stats.skills_used[sk] = stats.skills_used.get(sk, 0) + 1
            except (json.JSONDecodeError, TypeError):
                pass

        return stats

    def _parse_ts(self, ts_str: str) -> float:
        """Parse ISO timestamp string."""
        if not ts_str:
            return 0.0
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            return dt.timestamp()
        except (ValueError, AttributeError):
            return 0.0

    def insights_text(self, days: int = 30) -> str:
        """Return a formatted text summary."""
        stats = self.compute_stats(days)
        lines = [
            f"📊 Usage Insights (last {days} days)",
            f"Sessions: {stats.total_sessions}",
            f"Trajectories: {stats.total_trajectories}",
            f"Success rate: {stats.success_rate:.1%}",
            f"Total tokens: {stats.total_tokens:,}",
            f"Avg tokens/session: {stats.avg_tokens_per_session:,.0f}",
        ]
        if stats.skills_used:
            lines.append("Top skills:")
            for name, count in sorted(stats.skills_used.items(), key=lambda x: -x[1])[:5]:
                lines.append(f"  {name}: {count} uses")
        return "\n".join(lines)


__all__ = ["UsageInsights", "UsageStats"]
