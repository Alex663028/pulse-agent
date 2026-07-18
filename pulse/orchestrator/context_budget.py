"""Context budget: a hard guardrail against context-window overflow.

Tracks rolling token usage for a session. Crossing the soft threshold triggers
compaction (via the memory compactor); crossing the hard cap raises
``CtxOverflowError`` so the orchestrator can recover instead of silently
truncating or crashing.
"""

from __future__ import annotations

from typing import Optional

from pulse.llm.provider import LLMProvider
from pulse.orchestrator.recovery import CtxOverflowError


class ContextBudget:
    """Rolling token-budget guardrail with soft (compaction) and hard (overflow) thresholds."""

    def __init__(self, max_tokens: int = 12000, soft_ratio: float = 0.8):
        self.max_tokens = max_tokens
        self.soft = int(max_tokens * soft_ratio)
        self.used = 0

    def reserve(self, tokens: int) -> None:
        """Account for ``tokens`` of usage; raises ``CtxOverflowError`` past the hard cap."""
        self.used += tokens
        if self.used > self.max_tokens:
            raise CtxOverflowError(
                f"token budget exceeded: {self.used} > {self.max_tokens}"
            )

    @property
    def over_soft(self) -> bool:
        """True when usage has crossed the soft compaction threshold."""
        return self.used >= self.soft

    def fit(
        self, text: str, keep_tokens: int, llm: Optional[LLMProvider] = None
    ) -> str:
        """If over the soft threshold, compact ``text`` down to ``keep_tokens``."""
        from pulse.memory.compactor import compact

        if not self.over_soft:
            return text
        return compact(text, keep_tokens=keep_tokens, llm=llm)
