"""Model-agnostic LLM adapter.

All local / self-hosted endpoints (Ollama, vLLM, SGLang, LM Studio, LiteLLM
proxy) speak the OpenAI ``/v1/chat/completions`` protocol, so a single
``OpenAICompatProvider`` covers them. Cloud providers (OpenAI, OpenRouter,
DeepSeek, GLM, …) are the same protocol with an API key. Anthropic uses its
own SDK and is added as a sibling provider.
"""
from __future__ import annotations

import json
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
        """Send messages and return a normalized response."""

    def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> Iterator[LLMResponse]:
        """Stream chat completions (yields a single full response by default)."""
        yield self.chat(messages, tools=tools, tool_choice=tool_choice, **kwargs)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token for mixed content)."""
    return max(1, len(text) // 4)


class OpenAICompatProvider(LLMProvider):
    """OpenAI-compatible chat completions provider.

    Works with: OpenAI, OpenRouter, DeepSeek, Ollama, vLLM, SGLang, LM Studio,
    LiteLLM, SiliconFlow, and any other endpoint implementing the
    ``/v1/chat/completions`` protocol.
    """

    name = "openai-compat"

    def __init__(self, base_url: str, api_key: str = "", model: str = "", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
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
        """Stream chat completions (yields a final concatenated ``LLMResponse`` chunk per token)."""
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
    """Anthropic Messages API provider (Claude)."""

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
        self.api_mode = api_mode
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

        system = self._extract_system(messages)
        anthropic_tools = self._convert_tools(tools)
        conversation = self._convert_messages(messages)
        return self._invoke(system, conversation, anthropic_tools, tool_choice, **kwargs)

    def _extract_system(self, messages: list[LLMMessage]) -> str:
        system = ""
        for m in messages:
            if m.role == "system":
                system = m.content or ""
        return system

    @staticmethod
    def _convert_tools(tools: Optional[list[dict[str, Any]]]) -> list[dict[str, Any]]:
        if not tools:
            return []
        out: list[dict[str, Any]] = []
        for tool_def in tools:
            fn = tool_def.get("function", tool_def)
            param_schema = fn.get("parameters", {"type": "object", "properties": {}})
            out.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": param_schema,
            })
        return out

    @staticmethod
    def _convert_messages(messages: list[LLMMessage]) -> list[dict[str, Any]]:
        conversation: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "user":
                conversation.append({"role": "user", "content": m.content or ""})
            elif m.role == "assistant":
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
                    conversation.append({"role": "assistant", "content": m.content or ""})
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
        return conversation

    def _invoke(
        self,
        system: str,
        conversation: list[dict[str, Any]],
        anthropic_tools: list[dict[str, Any]],
        tool_choice: Optional[str],
        **kwargs: Any,
    ) -> LLMResponse:
        try:
            kwargs.setdefault("max_tokens", self.max_tokens)
            kwargs.setdefault("model", self.model)
            if anthropic_tools:
                kwargs["tools"] = anthropic_tools
            if tool_choice:
                kwargs["tool_choice"] = (
                    {"type": "auto"} if tool_choice == "auto"
                    else {"type": "tool", "name": tool_choice} if tool_choice == "tool"
                    else tool_choice
                )

            resp = self._client.messages.create(
                system=system or None,
                messages=conversation,
                **kwargs,
            )

            return self._parse_response(resp)
        except (RuntimeError, OSError, ValueError) as e:
            raise AnthropicError(f"anthropic request failed: {e}") from e

    @staticmethod
    def _parse_response(resp: Any) -> LLMResponse:
        content = ""
        tool_calls = []
        for block in resp.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))
        usage = Usage(
            prompt_tokens=getattr(resp.usage, "input_tokens", 0) or 0,
            completion_tokens=getattr(resp.usage, "output_tokens", 0) or 0,
        )
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            model=resp.model,
            usage=usage,
            finish_reason=resp.stop_reason or "end_turn",
        )
