"""Provider router with a fallback chain.

Reliability improvement over Hermes: a transient provider error does not kill
the task — the router walks the fallback chain (e.g. local Ollama -> OpenRouter
-> Anthropic) before surfacing a hard failure.
"""
from __future__ import annotations

from typing import Any, Optional

from pulse.llm.provider import LLMError, LLMMessage, LLMProvider, LLMResponse


class Router:
    """Routes chat calls to a primary provider, walking a fallback chain on ``LLMError``."""

    def __init__(self, primary: LLMProvider, fallbacks: Optional[list[LLMProvider]] = None):
        self.primary = primary
        self.fallbacks = list(fallbacks or [])

    def chat(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Try the primary then each fallback; raises ``LLMError`` only if every provider fails."""
        last_err: Optional[Exception] = None
        for idx, provider in enumerate([self.primary, *self.fallbacks]):
            try:
                return provider.chat(messages, tools=tools, tool_choice=tool_choice, **kwargs)
            except LLMError as e:
                last_err = e
                # primary failed -> try next; do not retry the same provider here
                continue
        raise LLMError(f"all providers failed (primary={self.primary.name}): {last_err}")

    @property
    def model(self) -> str:
        """Return the model identifier of the primary provider."""
        return self.primary.model
