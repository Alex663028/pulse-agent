"""Provider router with a fallback chain and rate limiting.

Reliability improvements over Hermes:
- A transient provider error does not kill the task — the router walks the
  fallback chain (e.g. local Ollama -> OpenRouter -> Anthropic) before
  surfacing a hard failure.
- A "bad" response (empty content, no tool_calls when tools were offered)
  triggers a retry on the next provider.
- Built-in token-bucket rate limiter prevents burst traffic that triggers 429s.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from pulse.llm.provider import (
    AnthropicError,
    LLMError,
    LLMMessage,
    LLMProvider,
    LLMResponse,
)

if TYPE_CHECKING:
    from pulse.orchestrator.rate_limiter import RateLimiter


class Router:
    """Routes chat calls to a primary provider, walking a fallback chain on failure or bad response."""

    def __init__(
        self,
        primary: LLMProvider,
        fallbacks: Optional[list[LLMProvider]] = None,
        rate_limiter: Optional["RateLimiter"] = None,
    ):
        self.primary = primary
        self.fallbacks = list(fallbacks or [])
        self._rate_limiter = rate_limiter

    def chat(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Try the primary then each fallback; raises LLMError only if every provider fails or returns a bad response."""
        has_tools = bool(tools)
        last_err: Optional[Exception] = None
        for idx, provider in enumerate([self.primary, *self.fallbacks]):
            # Rate limit before each provider call
            if self._rate_limiter:
                self._rate_limiter.before_call(provider.name)
            try:
                resp = provider.chat(messages, tools=tools, tool_choice=tool_choice, **kwargs)
                # Check for "bad" response: tools offered but model returned nothing useful
                if has_tools and not resp.has_tool_calls and not resp.content.strip():
                    continue  # bad response — try next provider
                return resp
            except (LLMError, AnthropicError) as e:
                last_err = e
                continue
        raise LLMError(f"all providers failed (primary={self.primary.name}): {last_err}")

    @property
    def model(self) -> str:
        """Return the model identifier of the primary provider."""
        return self.primary.model
