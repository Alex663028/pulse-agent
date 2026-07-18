"""Async-compatible LLM provider wrapper."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from pulse.llm.provider import LLMMessage, LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class AsyncLLMProvider:
    """Wraps a sync LLMProvider for async use.

    Uses asyncio.to_thread so sync providers (OpenAI, Anthropic)
    don't block the event loop.
    """

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    @property
    def name(self) -> str:
        return self._provider.name

    @property
    def model(self) -> str:
        return getattr(self._provider, "model", "")

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Async chat — runs the sync chat() in a thread pool."""
        return await asyncio.to_thread(
            self._provider.chat,
            messages,
            tools=tools,
            tool_choice=tool_choice,
            **kwargs,
        )

    def sync_chat(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Synchronous fallback."""
        return self._provider.chat(
            messages, tools=tools, tool_choice=tool_choice, **kwargs
        )


__all__ = ["AsyncLLMProvider"]
