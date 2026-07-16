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
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional


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

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class LLMError(Exception):
    """Raised by providers; classified by the orchestrator's recovery layer."""


class AnthropicError(Exception):
    """Raised by Anthropic provider."""


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

    def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> Iterator[LLMResponse]:
        """Yield incremental ``LLMResponse`` chunks (for streaming UIs).

        Default implementation falls back to a single non-streaming ``chat()``
        call. Providers that support streaming (OpenAI, Anthropic) should
        override this.
        """
        yield self.chat(messages, tools=tools, tool_choice=tool_choice, **kwargs)


def _estimate_tokens(text: str) -> int:
    # Cheap, deterministic approximation (~3.2 chars/token for English/code,
    # ~1.6 for CJK). Good enough for a budget guardrail, not for billing.
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    other = len(text) - cjk
    return max(1, cjk + int(other / 3.2))  # ~3.2 chars/token for English (was 4)


class OpenAICompatProvider(LLMProvider):
    """OpenAI-compatible chat completions provider (OpenAI, Ollama, OpenRouter, DeepSeek, etc.)."""

    name = "openai-compat"

    def __init__(self, base_url: str, api_key: str = "", model: str = "", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/") if base_url else base_url
        self.api_key = api_key or "not-needed"
        self.model = model
        self.timeout = timeout
        self._client = None

    def chat(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send messages to the OpenAI-compatible endpoint."""
        payload = self._build_payload(messages, tools, tool_choice, **kwargs)
        resp = self._execute_payload(payload)
        return self._parse_response(resp)

    def _build_payload(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict[str, Any]]],
        tool_choice: Optional[str],
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": kwargs.pop("model", self.model),
            "messages": [m.to_openai() for m in messages],
            "temperature": kwargs.get("temperature", 0.3),
            "max_tokens": kwargs.get("max_tokens", 4096),
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        return payload

    def _execute_payload(self, payload: dict[str, Any]) -> Any:
        try:
            if self._client is None:
                from openai import OpenAI

                self._client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=self.timeout)
            return self._client.chat.completions.create(**payload)
        except Exception as e:
            raise LLMError(f"openai-compat request failed: {e}") from e

    def _parse_response(self, resp: Any) -> LLMResponse:
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

    def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> Iterator[LLMResponse]:
        """Stream chat completions (yields a final concatenated ``LLMResponse`` chunk per token — best-effort, non-OpenAI-endpoints fall back to non-streaming)."""
        payload: dict[str, Any] = {
            "model": kwargs.pop("model", self.model),
            "messages": [m.to_openai() for m in messages],
            "temperature": kwargs.get("temperature", 0.3),
            "max_tokens": kwargs.get("max_tokens", 4096),
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        try:
            if self._client is None:
                from openai import OpenAI
                self._client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=self.timeout)
            stream = self._client.chat.completions.create(**payload)
            full_content = ""
            for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if choice and choice.delta.content:
                    full_content += choice.delta.content
                    yield LLMResponse(content=choice.delta.content)
                if choice and choice.delta.tool_calls:
                    for tc in choice.delta.tool_calls:
                        args_str = getattr(tc.function, "arguments", "{}")
                        try:
                            args = json.loads(args_str) if args_str else {}
                        except json.JSONDecodeError:
                            args = {}
                        yield LLMResponse(
                            tool_calls=[ToolCall(id=tc.id, name=tc.function.name, arguments=args)],
                        )
        except Exception:
            # fall back to non-streaming
            yield self.chat(messages, tools=tools, tool_choice=tool_choice, **kwargs)


class AnthropicProvider(LLMProvider):
    """Anthropic Messages API provider (Claude).

    Falls back to OpenAI protocol for non-Anthropic endpoints that
    mimic Anthropic's tool-use format (e.g. some local proxies).
    """

    name = "anthropic"

    def __init__(
        self,
        base_url: str = "https://api.anthropic.com",
        api_key: str = "",
        model: str = "claude-3-5-sonnet-20241022",
        max_tokens: int = 4096,
        api_mode: str = "messages",
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.api_mode = api_mode  # "messages" (Anthropic native) or "openai" (fallback)
        self._client = None

    def _ensure_client(self):
        """Lazily create the anthropic client on first use."""
        if self._client is None:
            try:
                import anthropic  # noqa: F811
                self._client = anthropic.Anthropic(base_url=self.base_url, api_key=self.api_key)
            except ImportError:
                self._client = "import_error"

    def chat(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self._ensure_client()
        if self._client == "import_error":
            raise LLMError("anthropic package not installed; pip install anthropic>=0.25")
        if self._client is None:
            raise LLMError("Anthropic client not initialized")

        # Build Anthropic system message from the system message if present
        system = ""
        filtered_messages: list[LLMMessage] = []
        for m in messages:
            if m.role == "system":
                system = m.content
            else:
                filtered_messages.append(m)

        # Convert tool definitions to Anthropic tool format
        anthropic_tools = []
        if tools:
            for tool_def in tools:
                fn = tool_def.get("function", tool_def)
                param_schema = fn.get("parameters", {"type": "object", "properties": {}})
                anthropic_tools.append({
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "input_schema": param_schema,
                })

        # Build conversation messages
        conversation = []
        for m in filtered_messages:
            if m.role == "user":
                conversation.append({"role": "user", "content": m.content or ""})
            elif m.role == "assistant":
                block = {"type": "text", "text": m.content or ""}
                if m.tool_calls:
                    for tc in m.tool_calls:
                        conversation.append({
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": m.content} if m.content else {"type": "text", "text": ""},
                                {
                                    "type": "tool_use",
                                    "id": tc.id,
                                    "name": tc.name,
                                    "input": tc.arguments,
                                },
                            ],
                        })
                else:
                    conversation.append({"role": "assistant", "content": [block]})
            elif m.role == "tool":
                conversation.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.tool_call_id or "",
                            "content": m.content or "",
                        }
                    ],
                })

        # Invoke the Anthropic API
        try:
            kwargs.setdefault("max_tokens", self.max_tokens)
            kwargs.setdefault("model", self.model)
            if tools:
                kwargs["tools"] = anthropic_tools
            if tool_choice:
                kwargs["tool_choice"] = (
                    {"type": "auto"} if tool_choice == "auto"
                    else {"type": "tool", "name": tool_choice} if tool_choice == "tool"
                    else tool_choice
                )

            resp = self._client.messages.create(
                system=system,
                messages=conversation,
                **kwargs,
            )

            # Convert Anthropic response to normalized LLMResponse
            tool_calls = []
            content_text = ""
            for block in resp.content:
                if block.type == "text":
                    content_text += block.text
                elif block.type == "tool_use":
                    tool_calls.append(ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input or {},
                    ))

            return LLMResponse(
                content=content_text,
                tool_calls=tool_calls,
                model=self.model,
                finish_reason=resp.stop_reason or "stop",
            )

        except Exception as e:
            raise AnthropicError(f"Anthropic API error: {e}") from e


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
        """Return a scripted/deterministic response, optionally emitting a tool call hinted by ``[call:name]`` in the user turn.

        ``_last_tool`` now tracks the last emitted tool; sessions can reset it
        by passing ``mock_reset=True`` in kwargs (not required for most tests).
        """
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
