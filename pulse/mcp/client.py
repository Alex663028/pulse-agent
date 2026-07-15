"""Lightweight MCP (Model Context Protocol) stdio client.

This integrates external MCP servers into Pulse's tool system without taking
a hard dependency on the official ``mcp`` SDK, keeping the project's
"lightweight, zero-cloud-dependency" positioning.

Only the **stdio** transport is supported (the most common way MCP servers
are launched). The protocol is newline-delimited JSON-RPC 2.0 over the
server's stdin/stdout; server logs go to stderr and are ignored.

A typical MCP server is started as a subprocess::

    npx -y @modelcontextprotocol/server-everything
    python -m some_mcp_server

Pulse connects, performs the ``initialize`` handshake, lists tools, and
exposes each one as a :class:`~pulse.tools.base.Tool` via :class:`MCPTool`.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from typing import Any, Optional

try:
    from pulse import __version__
except Exception:  # pragma: no cover - import safety
    __version__ = "0.2.0"

from pulse.tools.base import Tool, ToolResult

logger = logging.getLogger("pulse.mcp")

PROTOCOL_VERSION = "2024-11-05"


class MCPError(RuntimeError):
    """Raised when an MCP server returns an error or fails to respond."""


class MCPClient:
    """A stdio-based MCP client that manages a single server subprocess.

    Usage::

        client = MCPClient(command="npx", args=["-y", "@modelcontextprotocol/server-everything"])
        client.start()                      # launches + initialize handshake
        specs = client.list_tools()         # -> [{"name", "description", "inputSchema"}, ...]
        result = client.call_tool("echo", {"msg": "hi"})
        client.stop()
    """

    def __init__(
        self,
        command: str,
        args: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
        timeout: float = 30.0,
    ) -> None:
        self.command = command
        self.args = args or []
        self.env = env
        self.timeout = timeout
        self._proc: Optional[subprocess.Popen] = None
        self._req_id = 0
        self._lock = threading.Lock()
        self._responses: dict[int, dict[str, Any]] = {}
        self._read_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.server_info: dict[str, Any] = {}

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        """Launch the server subprocess and perform the initialize handshake."""
        try:
            self._proc = subprocess.Popen(
                [self.command, *self.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=self.env,
                text=True,
                bufsize=1,
            )
        except (OSError, ValueError) as e:
            raise MCPError(f"failed to launch MCP server '{self.command}': {e}") from e

        self._stop.clear()
        assert self._proc.stdout is not None
        self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._read_thread.start()

        # Perform the initialize handshake (raises on failure/timeout).
        resp = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "pulse", "version": __version__},
            },
        )
        if "error" in resp:
            self.stop()
            raise MCPError(f"initialize failed: {resp['error']}")
        self.server_info = resp.get("result", {}).get("serverInfo", {})
        # Notify the server that initialization is complete.
        self._request("notifications/initialized", notification=True)

    def _read_loop(self) -> None:
        """Continuously read JSON-RPC responses from stdout into ``_responses``."""
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                # Non-JSON output on stdout — ignore (logs belong on stderr).
                continue
            rid = msg.get("id")
            if rid is not None:
                self._responses[rid] = msg

    def _request(self, method: str, params: Any = None, *, notification: bool = False) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for the matching response."""
        if self._proc is None or self._proc.stdin is None:
            raise MCPError("MCP client is not started")
        with self._lock:
            self._req_id += 1
            rid = self._req_id
            req: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
            if not notification:
                req["id"] = rid
            if params is not None:
                req["params"] = params
            self._proc.stdin.write(json.dumps(req) + "\n")
            self._proc.stdin.flush()

            if notification:
                return {}

            deadline = time.time() + self.timeout
            while time.time() < deadline:
                if rid in self._responses:
                    return self._responses.pop(rid)
                time.sleep(0.02)
            raise MCPError(f"MCP request '{method}' timed out after {self.timeout}s")

    # -- public API ---------------------------------------------------------
    def list_tools(self) -> list[dict[str, Any]]:
        """Return the list of tools advertised by the server."""
        resp = self._request("tools/list")
        if "error" in resp:
            raise MCPError(f"tools/list failed: {resp['error']}")
        return resp.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke a tool on the server and return its raw result dict."""
        resp = self._request("tools/call", {"name": name, "arguments": arguments})
        if "error" in resp:
            return {"content": [{"type": "text", "text": str(resp["error"])}], "isError": True}
        return resp.get("result", {"content": [], "isError": False})

    def stop(self) -> None:
        """Terminate the server subprocess and join the reader thread."""
        self._stop.set()
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"error stopping MCP server: {e}")
        finally:
            self._proc = None

    # -- context manager ---------------------------------------------------
    def __enter__(self) -> "MCPClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()


class MCPTool(Tool):
    """Adapter that exposes a single MCP server tool as a Pulse ``Tool``."""

    def __init__(self, client: MCPClient, spec: dict[str, Any], server_name: str = "") -> None:
        self._client = client
        self._spec = spec
        self._server_name = server_name
        # Name used to *register* the tool (may be server-prefixed to avoid
        # collisions). The original server-side name is kept for invocation.
        self._server_tool_name = spec.get("name", "mcp_tool")
        self.name = self._server_tool_name
        self.description = spec.get("description", "")
        self.parameters = spec.get("inputSchema", {"type": "object", "properties": {}})

    def run(self, **kwargs: Any) -> ToolResult:
        """Call the underlying MCP tool and normalize its result."""
        try:
            result = self._client.call_tool(self._server_tool_name, kwargs)
        except MCPError as e:
            return ToolResult(ok=False, error=str(e))
        is_error = result.get("isError", False)
        parts: list[str] = []
        for block in result.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        text = "\n".join(p for p in parts if p)
        if is_error:
            return ToolResult(ok=False, output=text, error=text or "MCP tool error")
        return ToolResult(ok=True, output=text)


class MCPManager:
    """Connects to configured MCP servers and registers their tools globally."""

    def __init__(self, tools_registry: Any) -> None:
        self.tools = tools_registry
        self._clients: list[MCPClient] = []

    def load_servers(self, configs: list[Any]) -> int:
        """Start each enabled server, list its tools, and register them.

        Returns the number of MCP tools successfully registered.
        """
        registered = 0
        for cfg in configs:
            if getattr(cfg, "enabled", True) is False:
                continue
            try:
                client = MCPClient(command=cfg.command, args=list(cfg.args or []))
                client.start()
                specs = client.list_tools()
                for spec in specs:
                    tool = MCPTool(client, spec, server_name=cfg.name)
                    # Prefix name with server to avoid collisions across servers.
                    if cfg.name:
                        tool.name = f"{cfg.name}__{spec.get('name', 'tool')}"
                    self.tools.register(tool)
                    registered += 1
                self._clients.append(client)
                logger.info("Loaded %d MCP tools from '%s'", len(specs), cfg.name)
            except MCPError as e:
                logger.warning("MCP server '%s' failed: %s", getattr(cfg, "name", "?"), e)
            except Exception as e:  # noqa: BLE001
                logger.warning("MCP server '%s' error: %s", getattr(cfg, "name", "?"), e)
        return registered

    def shutdown(self) -> None:
        """Stop all connected MCP server subprocesses."""
        for client in self._clients:
            client.stop()
        self._clients.clear()
