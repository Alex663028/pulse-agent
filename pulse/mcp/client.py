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

Connection model
----------------
Server *discovery* (``tools/list``) happens once, in parallel, when the
manager is loaded — this keeps startup fast even with many servers. The
subprocess is then **disconnected**; it is only (re)spawned lazily the first
time one of its tools is actually invoked, and is cached for the session. If a
server crashes mid-session, the next call transparently reconnects.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

try:
    from pulse import __version__
except Exception:  # pragma: no cover - import safety
    __version__ = "0.3.0"

from pulse.tools.base import Tool, ToolResult

logger = logging.getLogger("pulse.mcp")

PROTOCOL_VERSION = "2024-11-05"

# JSON-schema type -> Python type(s) used for a lightweight argument check.
_JSON_TO_PY: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
    "null": (type(None),),
}


def validate_tool_args(schema: dict[str, Any] | None, args: dict[str, Any]) -> str | None:
    """Validate ``args`` against a JSON-schema ``inputSchema``.

    Returns an error message string if validation fails, or ``None`` if the
    arguments are acceptable. This is intentionally lightweight (required
    fields + loose JSON type checks) — it catches the common mistakes without
    pulling in a full schema validator.
    """
    if not schema:
        return None
    props = schema.get("properties") or {}
    required = schema.get("required") or []
    for name in required:
        if name not in args:
            return f"missing required argument: '{name}'"
    for key, value in args.items():
        meta = props.get(key)
        if not meta:
            continue
        json_type = meta.get("type")
        if json_type and json_type in _JSON_TO_PY:
            expected = _JSON_TO_PY[json_type]
            if not isinstance(value, expected):
                return f"argument '{key}' must be {json_type}, got {type(value).__name__}"
    return None


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

    def is_alive(self) -> bool:
        """Return True if the server subprocess is still running."""
        return self._proc is not None and self._proc.poll() is None

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


def probe_server(cfg: Any, timeout: float = 4.0) -> tuple[bool, int, str]:
    """Connect to a single MCP server, list its tools, and disconnect.

    Returns ``(ok, tool_count, detail)``. ``detail`` is a human-readable
    status string (e.g. ``"2 tool(s)"`` on success, or the error message on
    failure). The subprocess is always torn down, so this is safe to call for
    health checks without leaking processes.
    """
    try:
        client = MCPClient(command=cfg.command, args=list(cfg.args or []), timeout=timeout)
        client.start()
        try:
            specs = client.list_tools()
        finally:
            client.stop()
        return (True, len(specs), f"{len(specs)} tool(s)")
    except MCPError as e:
        return (False, 0, str(e))
    except Exception as e:  # noqa: BLE001
        return (False, 0, str(e))


class MCPTool(Tool):
    """Adapter that exposes a single MCP server tool as a Pulse ``Tool``.

    Two construction modes:

    * **Eager** — pass a live ``client`` (used in tests and direct use).
    * **Lazy** — pass ``manager`` + ``server_name``; the underlying server
      subprocess is (re)connected on demand and reconnects automatically if it
      crashes.
    """

    def __init__(
        self,
        client: MCPClient | None,
        spec: dict[str, Any],
        server_name: str = "",
        manager: "MCPManager | None" = None,
    ) -> None:
        self._client = client
        self._spec = spec
        self._server_name = server_name
        self._manager = manager
        # Name used to *invoke* the tool on the server (never prefixed).
        self._server_tool_name = spec.get("name", "mcp_tool")
        self.name = self._server_tool_name
        self.description = spec.get("description", "")
        self.parameters = spec.get("inputSchema", {"type": "object", "properties": {}})

    def _resolve_client(self) -> MCPClient:
        if self._client is not None:
            return self._client
        if self._manager is not None:
            return self._manager.ensure_connected(self._server_name)
        raise MCPError("MCPTool has no client and no manager")

    def run(self, **kwargs: Any) -> ToolResult:
        """Validate args, call the underlying MCP tool, and normalize its result."""
        err = validate_tool_args(self.parameters, kwargs)
        if err:
            return ToolResult(ok=False, error=err)
        try:
            client = self._resolve_client()
            result = client.call_tool(self._server_tool_name, kwargs)
        except MCPError as e:
            # The server may have died; try a single reconnect, then give up.
            if self._manager is not None:
                try:
                    client = self._manager.reconnect(self._server_name)
                    result = client.call_tool(self._server_tool_name, kwargs)
                except MCPError as e2:
                    return ToolResult(ok=False, error=f"MCP server '{self._server_name}' error: {e2}")
            else:
                return ToolResult(ok=False, error=f"MCP tool error: {e}")
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
    """Connects to configured MCP servers and registers their tools globally.

    Discovery is parallel and the server subprocesses are *not* held open —
    they are spawned lazily on first use and cached for the session, with
    automatic reconnection if a server dies.
    """

    def __init__(self, tools_registry: Any, probe_timeout: float = 10.0) -> None:
        self.tools = tools_registry
        self._configs: dict[str, Any] = {}
        self._clients: dict[str, MCPClient] = {}
        self._specs: dict[str, list[dict[str, Any]]] = {}
        self._errors: dict[str, str] = {}
        self._probe_timeout = probe_timeout

    def load_servers(self, configs: list[Any]) -> int:
        """Probe each enabled server (in parallel), register its tools, then
        disconnect. Servers are (re)connected lazily on first tool invocation.

        Returns the number of MCP tools successfully registered.
        """
        self._configs = {c.name: c for c in configs if getattr(c, "enabled", True)}
        registered = 0
        # Parallel probing keeps startup bounded by the *slowest* server rather
        # than the sum of all of them.
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(self._configs)))) as ex:
            futures = {name: ex.submit(self._probe, cfg) for name, cfg in self._configs.items()}
            for name, fut in futures.items():
                try:
                    specs = fut.result()
                except Exception as e:  # noqa: BLE001
                    self._errors[name] = str(e)
                    logger.warning("MCP server '%s' probe failed: %s", name, e)
                    continue
                self._specs[name] = specs
                for spec in specs:
                    tool = MCPTool(None, spec, server_name=name, manager=self)
                    # Prefix name with server to avoid collisions across servers.
                    if name:
                        tool.name = f"{name}__{spec.get('name', 'tool')}"
                    self.tools.register(tool)
                    registered += 1
                logger.info("Registered %d MCP tool(s) from '%s'", len(specs), name)
        return registered

    def _probe(self, cfg: Any) -> list[dict[str, Any]]:
        """Connect, list tools, and disconnect — used for discovery only."""
        client = MCPClient(command=cfg.command, args=list(cfg.args or []), timeout=self._probe_timeout)
        client.start()
        try:
            return client.list_tools()
        finally:
            client.stop()

    def ensure_connected(self, server_name: str) -> MCPClient:
        """Return a live client for ``server_name``, connecting on demand."""
        cfg = self._configs.get(server_name)
        if cfg is None:
            raise MCPError(f"unknown MCP server '{server_name}'")
        client = self._clients.get(server_name)
        if client is not None and client.is_alive():
            return client
        client = MCPClient(command=cfg.command, args=list(cfg.args or []))
        client.start()
        self._clients[server_name] = client
        return client

    def reconnect(self, server_name: str) -> MCPClient:
        """Force-drop any cached client and reconnect fresh."""
        self._clients.pop(server_name, None)
        return self.ensure_connected(server_name)

    def health(self) -> dict[str, dict[str, Any]]:
        """Return a per-server status summary (for CLI/doctor display)."""
        out: dict[str, dict[str, Any]] = {}
        for name, cfg in self._configs.items():
            client = self._clients.get(name)
            out[name] = {
                "enabled": True,
                "connected": client is not None and client.is_alive(),
                "tools": len(self._specs.get(name, [])),
                "error": self._errors.get(name),
            }
        return out

    def shutdown(self) -> None:
        """Stop all connected MCP server subprocesses."""
        for client in self._clients.values():
            client.stop()
        self._clients.clear()
