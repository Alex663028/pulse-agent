"""Core agent tools — expand the built-in toolkit beyond read-only operations.

This module provides the tools a self-improving agent actually needs to be useful:
web search, web fetch, code execution, HTTP requests, and file editing.
"""
from __future__ import annotations

import ast
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from pulse.tools.base import Tool, ToolResult


class WebSearchTool(Tool):
    """Search the web using DuckDuckGo's HTML interface (no API key required)."""

    name = "web_search"
    description = "Search the web for real-time information. Args: query (str), max_results (int, optional, default 5)."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query string"},
            "max_results": {"type": "integer", "description": "Maximum number of results (default 5, max 10)"},
        },
        "required": ["query"],
    }

    def run(self, query: str = "", max_results: int = 5, **kwargs: Any) -> ToolResult:
        """Search DuckDuckGo and return snippets."""
        try:
            max_results = min(max(1, int(max_results)), 10)
            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="replace")
                # Extract result snippets (DDG HTML format)
                results = []
                for part in html.split('<a rel="nofollow" class="result__a"')[1:]:
                    try:
                        href_start = part.index('href="') + 6
                        href_end = part.index('"', href_start)
                        href = part[href_start:href_end]
                        text_start = part.index('</a>') + 4
                        _ = part.index('</a>', text_start) if '</a>' in part[text_start:] else text_start + 200
                        text = part[text_start:].split("</a>")[0] if "</a>" in part[text_start:] else ""
                        text = text.strip()
                        if href and text:
                            results.append(f"Title: {text[:100]}\nURL: {href}")
                            if len(results) >= max_results:
                                break
                    except (ValueError, IndexError):
                        continue
                if not results:
                    # Fallback: look for any links
                    for line in html.split("\n"):
                        if "result__snippet" in line:
                            snippet = line.split(">")[1].split("<")[0].strip()
                            if snippet:
                                results.append(snippet)
                                if len(results) >= max_results:
                                    break
                if not results:
                    return ToolResult(ok=False, error="No search results found")
                return ToolResult(ok=True, output="\n\n".join(results))
        except Exception as e:
            return ToolResult(ok=False, error=f"search failed: {e}")


class WebFetchTool(Tool):
    """Fetch content from a URL and return plain text."""

    name = "web_fetch"
    description = "Fetch content from a URL (HTML → text). Args: url (str), max_chars (int, optional, default 5000)."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "HTTP or HTTPS URL to fetch"},
            "max_chars": {"type": "integer", "description": "Maximum characters to return (default 5000)"},
        },
        "required": ["url"],
    }

    def run(self, url: str = "", max_chars: int = 5000, **kwargs: Any) -> ToolResult:
        """Fetch URL content and return plain text."""
        try:
            max_chars = max(100, int(max_chars))
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                # Remove scripts, styles
                import re
                raw = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
                raw = re.sub(r"<style[^>]*>.*?</style>", "", raw, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r"<[^>]+>", " ", raw)
                text = re.sub(r"\s+", " ", text).strip()
                if not text:
                    return ToolResult(ok=False, error="No text content at URL")
                return ToolResult(ok=True, output=text[:max_chars])
        except Exception as e:
            return ToolResult(ok=False, error=f"fetch failed: {e}")


class WriteFileTool(Tool):
    """Write text content to a file (UTF-8, creates parent dirs)."""

    name = "write_file"
    description = "Write text content to a file (creates parent dirs). Args: path (str), content (str)."

    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to write"},
            "content": {"type": "string", "description": "Text content to write"},
        },
        "required": ["path", "content"],
    }

    def run(self, path: str = "", content: str = "", **kwargs: Any) -> ToolResult:
        """Write ``content`` to ``path``, creating parent directories."""
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return ToolResult(ok=True, output=f"wrote {len(content)} chars to {path}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class EditFileTool(Tool):
    """Edit a file using find-and-replace (exact match)."""

    name = "edit_file"
    description = "Edit a file by replacing exact text. Args: path (str), old_string (str), new_string (str)."

    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path to edit"},
            "old_string": {"type": "string", "description": "Exact text to find"},
            "new_string": {"type": "string", "description": "Replacement text"},
        },
        "required": ["path", "old_string", "new_string"],
    }

    def run(self, path: str = "", old_string: str = "", new_string: str = "", **kwargs: Any) -> ToolResult:
        """Replace ``old_string`` with ``new_string`` in file ``path``."""
        try:
            p = Path(path)
            if not p.exists():
                return ToolResult(ok=False, error=f"no such file: {path}")
            content = p.read_text(encoding="utf-8")
            if old_string not in content:
                return ToolResult(ok=False, error="old_string not found in file")
            new_content = content.replace(old_string, new_string)
            p.write_text(new_content, encoding="utf-8")
            return ToolResult(ok=True, output=f"edited {path}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PythonExecTool(Tool):
    """Safely execute Python code and return stdout."""

    name = "python_exec"
    description = "Execute Python code and return stdout. Args: code (str), timeout (int, optional, default 5)."

    parameters = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"},
            "timeout": {"type": "integer", "description": "Max execution seconds (default 5, max 30)"},
        },
        "required": ["code"],
    }

    def run(self, code: str = "", timeout: int = 5, **kwargs: Any) -> ToolResult:
        """Execute Python code in a subprocess and return stdout."""
        try:
            timeout = max(1, min(int(timeout), 30))
            # Minimal AST safety check
            try:
                ast.parse(code)
            except SyntaxError as se:
                return ToolResult(ok=False, error=f"syntax error: {se}")
            result = subprocess.run(
                ["python", "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = result.stdout.strip() + (f"\n[stderr] {result.stderr.strip()}" if result.stderr.strip() else "")
            if result.returncode != 0:
                return ToolResult(ok=False, error=f"exit {result.returncode}: {output}")
            return ToolResult(ok=True, output="(no output)" if not output else output)
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, error=f"timeout after {timeout}s")
        except FileNotFoundError:
            return ToolResult(ok=False, error="python not found on PATH")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ShellExecTool(Tool):
    """Execute a shell command and return stdout."""

    name = "shell_exec"
    description = "Execute a shell command and return stdout. Args: command (str), timeout (int, optional, default 10)."

    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout": {"type": "integer", "description": "Max execution seconds (default 10, max 60)"},
        },
        "required": ["command"],
    }

    def run(self, command: str = "", timeout: int = 10, **kwargs: Any) -> ToolResult:
        """Execute a shell command and return stdout (best-effort)."""
        try:
            timeout = max(1, min(int(timeout), 60))
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = result.stdout.strip() + (f"\n[stderr] {result.stderr.strip()}" if result.stderr.strip() else "")
            if result.returncode != 0:
                return ToolResult(ok=False, error=f"exit {result.returncode}: {output}")
            return ToolResult(ok=True, output="(no output)" if not output else output)
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, error=f"timeout after {timeout}s")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class HttpClientTool(Tool):
    """Simple HTTP client for API calls."""

    name = "http_client"
    description = "Make HTTP requests. Args: url (str), method (str, default GET), headers (dict, optional), body (str, optional)."

    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "HTTP/HTTPS URL"},
            "method": {"type": "string", "description": "HTTP method: GET, POST, PUT, DELETE (default GET)"},
            "headers": {"type": "object", "description": "Request headers as dict"},
            "body": {"type": "string", "description": "Request body (POST/PUT)"},
            "timeout": {"type": "integer", "description": "Timeout seconds (default 15)"},
        },
        "required": ["url"],
    }

    def run(
        self,
        url: str = "",
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: str | None = None,
        timeout: int = 15,
        **kwargs: Any,
    ) -> ToolResult:
        """Make an HTTP request and return status + body."""
        try:
            method = method.upper()
            data = body.encode() if body else None
            req = urllib.request.Request(url, data=data, method=method)
            if headers:
                for k, v in headers.items():
                    req.add_header(k, v)
            req.add_header("User-Agent", "Pulse-Agent/1.0")
            timeout = max(1, min(int(timeout), 60))
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_body = resp.read().decode("utf-8", errors="replace")[:5000]
                return ToolResult(
                    ok=True,
                    output=f"Status: {resp.status}\n\n{resp_body}",
                )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))
