"""Model-agnostic LLM adapter.

All local / self-hosted endpoints (Ollama, vLLM, SGLang, LM Studio, LiteLLM
proxy) speak the OpenAI ``/v1/chat/completions`` protocol, so a single
``OpenAICompatProvider`` covers them. Cloud providers (OpenAI, OpenRouter,
DeepSeek, GLM, …) are the same protocol with an API key. Anthropic uses its
own SDK and is added as a sibling provider.

A built-in ``MockProvider`` lets the whole stack run fully offline for tests
and demos without any model server.
"""
from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolCall:
    """A single LLM-issued tool call: id, function name and parsed arguments."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMMessage:
    """A chat message in the OpenAI-compatible format (system/user/assistant/tool)."""

    role: str  # system | user | assistant | tool
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    name: Optional[str] = None  # tool name when role == "tool"
    tool_call_id: Optional[str] = None

    def to_openai(self) -> dict[str, Any]:
        """Render this message as an OpenAI API payload dict (including tool_calls when present)."""
        msg: dict[str, Any] = {"role": self.role, "content": self.content or ""}
        if self.role == "tool":
            msg["tool_call_id"] = self.tool_call_id
            msg["name"] = self.name
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
                }
                for tc in self.tool_calls
            ]
        return msg


@dataclass
class Usage:
    """Token accounting for a single LLM response."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        """Total tokens used (prompt + completion)."""
        return self.prompt_tokens + self.completion_tokens


@dataclass
class LLMResponse:
    """A normalized LLM response: content, tool_calls, model name, usage and finish_reason."""

    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    usage: Usage = field(default_factory=Usage)
    finish_reason: str = "stop"


class LLMError(Exception):
    """Raised by providers; classified by the orchestrator's recovery layer."""


class LLMProvider(ABC):
    """Abstract base for all LLM providers (chat returns a normalized ``LLMResponse``)."""

    name: str = "base"

    @abstractmethod
    def chat(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Run a chat completion against the underlying model and return a normalized ``LLMResponse``."""


def _estimate_tokens(text: str) -> int:
    # Cheap, deterministic approximation (~4 chars/token for English/code,
    # ~1.6 for CJK). Good enough for a budget guardrail, not for billing.
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    other = len(text) - cjk
    return max(1, cjk + other // 4)


class OpenAICompatProvider(LLMProvider):
    """Covers Ollama / vLLM / OpenRouter / OpenAI / DeepSeek / LiteLLM proxy."""

    name = "openai-compat"

    def __init__(self, base_url: str, api_key: str = "", model: str = "", timeout: float = 120.0):
        from openai import OpenAI

        self.base_url = base_url
        self.api_key = api_key or "not-needed"
        self.model = model
        self._client = OpenAI(base_url=base_url, api_key=self.api_key, timeout=timeout)

    def chat(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send messages to the OpenAI-compatible endpoint and parse the response into ``LLMResponse`` (raises ``LLMError`` on transport failures)."""
        payload: dict[str, Any] = {
            "model": kwargs.pop("model", self.model),
            "messages": [m.to_openai() for m in messages],
            "temperature": kwargs.get("temperature", 0.3),
            "max_tokens": kwargs.get("max_tokens", 4096),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        try:
            resp = self._client.chat.completions.create(**payload)
        except Exception as e:  # network / rate-limit / 5xx -> recoverable
            raise LLMError(f"openai-compat request failed: {e}") from e
        choice = resp.choices[0]
        msg = choice.message
        tool_calls = []
        for tc in getattr(msg, "tool_calls", None) or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        usage = Usage(
            prompt_tokens=getattr(resp.usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(resp.usage, "completion_tokens", 0) or 0,
        )
        return LLMResponse(
            content=msg.content or "",
            tool_calls=tool_calls,
            model=resp.model,
            usage=usage,
            finish_reason=choice.finish_reason or "stop",
        )


class MockProvider(LLMProvider):
    """Offline provider.

    - If ``tools`` are supplied and the prompt contains a bracketed hint like
      ``[call:tool_name]``, it emits that tool call (used by tests).
    - Otherwise it returns a deterministic, templated answer and records fake
      token usage so the context-budget guardrail is exercised end-to-end.
    """

    name = "mock"

    def __init__(self, model: str = "mock-1", scripted: Optional[list[LLMResponse]] = None):
        self.model = model
        self.scripted = list(scripted or [])
        self.calls: list[list[LLMMessage]] = []
        self._last_tool: Optional[str] = None

    def chat(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Return a scripted/deterministic response, optionally emitting a tool call hinted by ``[call:name]`` in the user turn."""
        self.calls.append(list(messages))
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        if self.scripted:
            return self.scripted.pop(0)
        if tools:
            m = re.search(r"\[call:([\w\-]+)\]", last_user)
            # emit a given tool call at most once per task to avoid loops
            if m and m.group(1) != self._last_tool:
                self._last_tool = m.group(1)
                return LLMResponse(
                    content="",
                    tool_calls=[ToolCall(id="call_1", name=m.group(1), arguments={"query": last_user})],
                    model=self.model,
                )
        answer = f"[mock] Acknowledged: {last_user[:120]}"
        return LLMResponse(
            content=answer,
            model=self.model,
            usage=Usage(prompt_tokens=_estimate_tokens(last_user), completion_tokens=_estimate_tokens(answer)),
        )
