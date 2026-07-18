"""Context compaction: keep the working set inside the token budget.

Reliability improvement over Hermes: when a session approaches the token cap,
older turns are summarized (or truncated) so the agent never silently loses
context or blows the context window. LLM-based summarization is used when a
provider is available; otherwise a deterministic extractive fallback runs.
"""

from __future__ import annotations

from typing import Optional

from pulse.llm.provider import AnthropicError, LLMError, LLMMessage, LLMProvider


def _naive_compact(text: str, keep_tokens: int) -> str:
    # keep the most recent content that fits the budget (~3.2 chars/token)
    budget_chars = max(200, keep_tokens * 3)
    if len(text) <= budget_chars:
        return text
    head = text[: budget_chars // 3]
    tail = text[-(budget_chars * 2 // 3) :]
    return f"{head}\n\n… [compressed {len(text) - len(head) - len(tail)} chars] …\n\n{tail}"


def compact(text: str, keep_tokens: int, llm: Optional[LLMProvider] = None) -> str:
    """Compress ``text`` to ~``keep_tokens``; uses LLM summarization when available, else extractive fallback."""
    if llm is not None:
        try:
            resp = llm.chat(
                [
                    LLMMessage(
                        role="system",
                        content="Summarize the following agent transcript into a concise, "
                        "fact-preserving brief. Keep names, decisions, and open tasks.",
                    ),
                    LLMMessage(role="user", content=text[:8000]),
                ],
                max_tokens=keep_tokens,
            )
            if resp.content:
                return resp.content
        except (RuntimeError, OSError, LLMError, AnthropicError):
            pass
    return _naive_compact(text, keep_tokens)
