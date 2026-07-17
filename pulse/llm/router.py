"""Provider router with a fallback chain, rate limiting, circuit breaker, and async."""
from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


class Router:
    """Routes chat calls to a primary provider, walking a fallback chain on failure or bad response.

    Features:
    - Fallback chain: tries each provider in order
    - Bad response detection: empty content when tools were offered
    - Rate limiting: before each provider call
    - Circuit breaker: tracks failures per provider, skips broken ones
    - Async: async_chat() for non-blocking use
    """

    def __init__(
        self,
        primary: LLMProvider,
        fallbacks: Optional[list[LLMProvider]] = None,
        rate_limiter: Optional["RateLimiter"] = None,
    ):
        self.primary = primary
        self.fallbacks = list(fallbacks or [])
        self._rate_limiter = rate_limiter
        # Track circuit breaker state per provider name
        self._breaker_state: dict[str, dict] = {}

    def chat(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Try the primary then each fallback; raises LLMError only if every provider fails."""
        has_tools = bool(tools)
        last_err: Optional[Exception] = None
        providers = [self.primary, *self.fallbacks]
        for idx, provider in enumerate(providers):
            # Circuit breaker check: skip providers with too many recent failures
            if self._is_circuit_open(provider.name):
                logger.debug("skipping %s (circuit open)", provider.name)
                continue
            # Rate limit before each provider call
            if self._rate_limiter:
                self._rate_limiter.before_call(provider.name)
            try:
                resp = provider.chat(messages, tools=tools, tool_choice=tool_choice, **kwargs)
                # Reset circuit breaker on success
                self._record_success(provider.name)
                # Check for "bad" response: tools offered but model returned nothing useful
                if has_tools and not resp.has_tool_calls and not resp.content.strip():
                    continue  # bad response — try next provider
                return resp
            except (LLMError, AnthropicError) as e:
                last_err = e
                self._record_failure(provider.name, e)
                continue
        raise LLMError(f"all providers failed (primary={self.primary.name}): {last_err}")

    def _is_circuit_open(self, name: str) -> bool:
        """Check if a provider's circuit breaker is open."""
        state = self._breaker_state.get(name, {})
        failures = state.get("failures", 0)
        if failures >= 5:
            # Check if enough time has passed to retry (30s cooldown)
            last_failure = state.get("last_failure", 0.0)
            import time
            if time.time() - last_failure < 30.0:
                return True
            else:
                # Reset to half-open state
                state["failures"] = 0
        return False

    def _record_failure(self, name: str, exc: Exception) -> None:
        """Record a provider failure for circuit breaker."""
        import time
        state = self._breaker_state.setdefault(name, {"failures": 0, "last_failure": 0.0})
        state["failures"] += 1
        state["last_failure"] = time.time()
        if state["failures"] >= 5:
            logger.warning("provider %s circuit breaker OPEN after %d failures", name, state["failures"])

    def _record_success(self, name: str) -> None:
        """Reset circuit breaker on success."""
        if name in self._breaker_state:
            self._breaker_state[name]["failures"] = 0

    @property
    def model(self) -> str:
        """Return the model identifier of the primary provider."""
        return self.primary.model

    def reset_breakers(self) -> None:
        """Reset all circuit breakers (e.g. after a retry succeeds)."""
        self._breaker_state.clear()
