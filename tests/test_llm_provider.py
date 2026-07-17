"""Tests for LLM provider module."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pulse.llm.provider import (
    AnthropicProvider,
    LLMMessage,
    LLMResponse,
    OpenAICompatProvider,
    ToolCall,
)


class TestOpenAICompatProvider:
    """Test OpenAICompatProvider."""

    def test_init(self):
        """OpenAICompatProvider initialization."""
        provider = OpenAICompatProvider(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            model="gpt-4",
        )
        assert provider.model == "gpt-4"

    def test_extract_messages_passthrough(self):
        """OpenAICompatProvider passes messages to OpenAI as-is."""
        provider = OpenAICompatProvider(base_url="http://localhost/v1")
        messages = [
            LLMMessage(role="system", content="You are helpful"),
            LLMMessage(role="user", content="Hello"),
        ]
        payload = provider._build_payload(messages, None, None)
        assert len(payload["messages"]) == 2

    def test_extract_no_system(self):
        """_build_payload with no system messages."""
        provider = OpenAICompatProvider(base_url="http://localhost/v1")
        messages = [LLMMessage(role="user", content="Hello")]
        payload = provider._build_payload(messages, None, None)
        assert len(payload["messages"]) == 1

    def test_build_payload_basic(self):
        """_build_payload creates correct structure."""
        provider = OpenAICompatProvider(base_url="http://localhost/v1", model="gpt-4")
        messages = [LLMMessage(role="user", content="Hello")]
        payload = provider._build_payload(messages, None, None)
        assert payload["model"] == "gpt-4"

    def test_build_payload_with_tools(self):
        """_build_payload with tools."""
        provider = OpenAICompatProvider(base_url="http://localhost/v1", model="gpt-4")
        messages = [LLMMessage(role="user", content="Hello")]
        tools = [{"function": {"name": "echo"}}]
        payload = provider._build_payload(messages, tools, None)
        assert "tools" in payload

    def test_payload_passes_system_through(self):
        """_build_payload passes system messages as-is (OpenAI format)."""
        provider = OpenAICompatProvider(base_url="http://localhost/v1", model="gpt-4")
        messages = [
            LLMMessage(role="system", content="You are helpful"),
            LLMMessage(role="user", content="Hello"),
        ]
        payload = provider._build_payload(messages, None, None)
        assert len(payload["messages"]) == 2

    def test_parse_response_basic(self):
        """_parse_response extracts content."""
        provider = OpenAICompatProvider(base_url="http://localhost/v1")
        mock_resp = MagicMock()
        mock_resp.model = "gpt-4"
        mock_resp.usage = MagicMock()
        mock_resp.usage.prompt_tokens = 10
        mock_resp.usage.completion_tokens = 5
        mock_resp.usage.total_tokens = 15
        choice = MagicMock()
        choice.message.content = "Hello back"
        choice.message.tool_calls = None
        choice.finish_reason = "stop"
        mock_resp.choices = [choice]
        resp = provider._parse_response(mock_resp)
        assert resp.content == "Hello back"

    def test_parse_response_with_tool_calls(self):
        """_parse_response extracts tool calls."""
        provider = OpenAICompatProvider(base_url="http://localhost/v1")
        mock_resp = MagicMock()
        mock_resp.model = "gpt-4"
        mock_resp.usage = MagicMock()
        mock_resp.usage.prompt_tokens = 10
        mock_resp.usage.completion_tokens = 5
        mock_resp.usage.total_tokens = 15
        tool_call = MagicMock()
        tool_call.id = "call_123"
        tool_call.function.name = "echo"
        tool_call.function.arguments = '{"text": "hello"}'
        choice = MagicMock()
        choice.message.content = ""
        choice.message.tool_calls = [tool_call]
        choice.finish_reason = "tool_calls"
        mock_resp.choices = [choice]
        resp = provider._parse_response(mock_resp)
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "echo"

    def test_chat_calls_execute(self):
        """chat() calls _execute_payload."""
        provider = OpenAICompatProvider(base_url="http://localhost/v1")
        with patch.object(provider, "_execute_payload") as mock_exec, \
             patch.object(provider, "_parse_response") as mock_parse:
            mock_exec.return_value = MagicMock()
            mock_parse.return_value = LLMResponse(content="test")
            result = provider.chat([LLMMessage(role="user", content="hi")])
            assert result.content == "test"
            mock_exec.assert_called_once()


class TestAnthropicProvider:
    """Test AnthropicProvider."""

    def test_init(self):
        """AnthropicProvider initialization."""
        provider = AnthropicProvider(
            api_key="test-key",
            model="claude-3-5-sonnet-20241022",
        )
        assert provider.name == "anthropic"
        assert provider.model == "claude-3-5-sonnet-20241022"

    def test_ensure_client_import_error(self):
        """_ensure_client handles import error."""
        provider = AnthropicProvider()
        with patch.dict("sys.modules", {"anthropic": None}):
            provider._ensure_client()
            assert provider._client == "import_error"

    def test_chat_raises_on_no_anthropic(self):
        """chat raises when anthropic is not installed."""
        provider = AnthropicProvider()
        provider._client = "import_error"
        with pytest.raises(Exception) as exc:
            provider.chat([LLMMessage(role="user", content="hi")])
        assert "anthropic" in str(exc.value).lower()

    def test_convert_tools(self):
        """_convert_tools formats tools for Anthropic format."""
        provider = AnthropicProvider()
        tools = [{"function": {"name": "echo", "parameters": {"type": "object"}}}]
        result = provider._convert_tools(tools)
        assert len(result) == 1
        assert result[0]["name"] == "echo"
        assert "input_schema" in result[0]

    def test_convert_tools_empty(self):
        """_convert_tools handles empty."""
        provider = AnthropicProvider()
        assert provider._convert_tools(None) == []
        assert provider._convert_tools([]) == []

    def test_convert_messages_user(self):
        """_convert_messages handles user messages."""
        provider = AnthropicProvider()
        messages = [LLMMessage(role="user", content="hello")]
        result = provider._convert_messages(messages)
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "hello"

    def test_convert_messages_assistant_with_tool_calls(self):
        """_convert_messages handles assistant with tool calls."""
        provider = AnthropicProvider()
        messages = [
            LLMMessage(
                role="assistant",
                content="Using tool",
                tool_calls=[ToolCall(id="tc1", name="echo", arguments={"text": "hi"})],
            )
        ]
        result = provider._convert_messages(messages)
        assert result[0]["role"] == "assistant"
        assert any(c.get("type") == "tool_use" for c in result[0]["content"])

    def test_convert_messages_tool_response(self):
        """_convert_messages handles tool result messages."""
        provider = AnthropicProvider()
        messages = [
            LLMMessage(role="tool", content="result", tool_call_id="tc1"),
        ]
        result = provider._convert_messages(messages)
        assert result[0]["role"] == "user"
        assert result[0]["content"][0]["type"] == "tool_result"

    def test_extract_system(self):
        """_extract_system extracts system message."""
        provider = AnthropicProvider()
        messages = [
            LLMMessage(role="system", content="You are Claude"),
            LLMMessage(role="user", content="Hi"),
        ]
        system, filtered = provider._extract_system(messages)
        assert system == "You are Claude"
        assert len(filtered) == 1

    def test_invoke_with_tools(self):
        """_invoke passes tools to API."""
        provider = AnthropicProvider()
        provider._client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.content = []
        mock_resp.stop_reason = "end_turn"
        mock_resp.usage = MagicMock()
        mock_resp.usage.input_tokens = 10
        mock_resp.usage.output_tokens = 5
        mock_resp.model = "claude-3"
        provider._client.messages.create.return_value = mock_resp
        with patch.object(provider, "_parse_response") as mock_parse:
            mock_parse.return_value = LLMResponse(content="hi")
            provider._invoke("", [], [], None)
            provider._client.messages.create.assert_called_once()
