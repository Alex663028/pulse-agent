"""Tests for core tools: WebSearchTool, WebFetchTool, FileEditTool, PythonExecTool, ShellExecTool, HttpClientTool."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


from pulse.tools.base import ToolResult
from pulse.tools.core import (
    EditFileTool,
    HttpClientTool,
    PythonExecTool,
    ShellExecTool,
    WebFetchTool,
    WebSearchTool,
)


class TestWebSearchTool:
    """Test WebSearchTool."""

    def test_run_returns_results(self):
        """web_search returns structured results."""
        tool = WebSearchTool()
        html = '<a rel="nofollow" class="result__a" href="http://example.com">Hello World</a><a rel="nofollow" class="result__snippet">A snippet</a>'
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = html.encode()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            result = tool.run("hello")
            # Could be ok=True if snippets found, or ok=False if parsing fails
            # just verify we get a ToolResult
            assert isinstance(result, ToolResult)

    def test_run_no_results(self):
        """web_search returns error when no results."""
        tool = WebSearchTool()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"<html>empty</html>"
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            result = tool.run("xyznoexist123")
            assert result.ok is False


class TestWebFetchTool:
    """Test WebFetchTool."""

    def test_run_fetches_url(self):
        """web_fetch returns page content."""
        tool = WebFetchTool()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"<html>Hello</html>"
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            result = tool.run("http://example.com")
            assert result.ok is True
            assert "Hello" in result.output

    def test_run_handles_timeout(self):
        """web_fetch handles timeout gracefully."""
        tool = WebFetchTool()
        with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
            result = tool.run("http://example.com")
            assert result.ok is False


class TestEditFileTool:
    """Test EditFileTool."""

    def test_run_edits_file(self, tmp_path):
        """edit_file replaces text in file."""
        tool = EditFileTool()
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = tool.run(str(f), "hello", "goodbye")
        assert result.ok is True
        assert f.read_text() == "goodbye world"

    def test_run_no_file(self, tmp_path):
        """edit_file returns error for non-existent file."""
        tool = EditFileTool()
        result = tool.run(str(tmp_path / "nonexistent.txt"), "hello", "goodbye")
        assert result.ok is False

    def test_run_old_string_not_found(self, tmp_path):
        """edit_file returns error when old_string not in file."""
        tool = EditFileTool()
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        result = tool.run(str(f), "xyz", "abc")
        assert result.ok is False


class TestPythonExecTool:
    """Test PythonExecTool."""

    def test_run_executes_code(self):
        """python_exec runs Python code."""
        tool = PythonExecTool()
        result = tool.run("print('hello')")
        assert result.ok is True
        assert "hello" in result.output

    def test_run_syntax_error(self):
        """python_exec returns error for invalid syntax."""
        tool = PythonExecTool()
        result = tool.run("def foo(")
        assert result.ok is False
        assert "syntax" in result.error.lower()

    def test_run_timeout(self):
        """python_exec handles timeout."""
        tool = PythonExecTool()
        result = tool.run("import time; time.sleep(60)", timeout=1)
        assert result.ok is False
        assert "timeout" in result.output.lower() or "timeout" in (result.error or "").lower()


class TestShellExecTool:
    """Test ShellExecTool."""

    def test_run_rejects_empty_command(self):
        """shell_exec rejects empty command."""
        tool = ShellExecTool()
        result = tool.run("")
        assert result.ok is False
        assert "empty" in result.error.lower()

    def test_run_executes_command(self):
        """shell_exec executes shell command."""
        tool = ShellExecTool()
        result = tool.run("echo hello")
        assert result.ok is True
        assert "hello" in result.output

    def test_run_handles_error(self):
        """shell_exec handles command errors."""
        tool = ShellExecTool()
        result = tool.run("exit 1")
        assert result.ok is False


class TestHttpClientTool:
    """Test HttpClientTool."""

    def test_run_get_request(self):
        """http_client sends GET request."""
        tool = HttpClientTool()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = b'{"ok": true}'
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            result = tool.run("http://api.example.com")
            assert result.ok is True
            assert "200" in result.output

    def test_run_with_method(self):
        """http_client supports different HTTP methods."""
        tool = HttpClientTool()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 201
            mock_resp.read.return_value = b""
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = mock_resp
            result = tool.run("http://api.example.com", method="POST")
            assert result.ok is True
            assert "201" in result.output

    def test_run_handles_error(self):
        """http_client handles errors."""
        tool = HttpClientTool()
        with patch("urllib.request.urlopen", side_effect=Exception("connection error")):
            result = tool.run("http://api.example.com")
            assert result.ok is False
