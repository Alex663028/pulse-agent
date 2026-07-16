"""Lightweight MCP (Model Context Protocol) stdio client — stability improvements.

Improvements over original:
- Reconnect with exponential backoff (up to 5 retries)
- Background health-check polling (detects server crashes)
- stderr captured to a ring buffer for debugging
- Graceful handling of subprocess crashes mid-request
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from collections import deque
from typing import Any, Optional

try:
    from pulse import __version__
except Exception:
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
    """Validate ``args`` against a JSON-schema ``inputSchema``."""
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

    Features:
    - Automatic reconnect with exponential backoff
    - Health-check polling (background thread)
    - stderr ring buffer for debugging
    - Crash-resilient request handling

    Usage::

        client = MCPClient(command="npx", args=["-y", "@modelcontextprotocol/server-everything"])
        client.start()
        specs = client.list_tools()
        result = client.call_tool("echo", {"msg": "hi"})
        client.stop()
    """

    def __init__(
        self,
        command: str,
        args: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
        timeout: float = 30.0,
        max_retries: int = 5,
        health_check_interval: float = 10.0,
    ) -> None:
        self.command = command
        self.args = args or []
        self.env = env
        self.timeout = timeout
        self.max_retries = max_retries
        self.health_check_interval = health_check_interval
        self._proc: Optional[subprocess.Popen] = None
        self._req_id = 0
        self._lock = threading.Lock()
        self._responses: dict[int, dict[str, Any]] = {}
        self._read_thread: Optional[threading.Thread] = None
        self._health_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.server_info: dict[str, Any] = {}
        self._stderr_buffer: deque[str] = deque(maxlen=100)
        self._stderr_thread: Optional[threading.Thread] = None
        self._consecutive_failures = 0

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Launch the server subprocess and perform the initialize handshake.

        On failure, retries up to ``max_retries`` times with exponential backoff.
        """
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                self._launch()
                self._do_initialize()
                self._consecutive_failures = 0
                self._start_health_thread()
                return
            except MCPError as e:
                last_error = e
                logger.warning(
                    "MCP server start attempt %d/%d failed: %s",
                    attempt + 1, self.max_retries, e,
                )
                self._cleanup_proc()
                if attempt < self.max_retries - 1:
                    wait = min(2 ** attempt, 10)
                    time.sleep(wait)
        raise MCPError(f"failed to start MCP server after {self.max_retries} attempts: {last_error}")

    def _launch(self) -> None:
        """Start the subprocess and reader threads."""
        try:
            self._proc = subprocess.Popen(
                [self.command, *self.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.env,
                text=True,
                bufsize=1,
            )
        except (OSError, ValueError) as e:
            raise MCPError(f"failed to launch MCP server '{self.command}': {e}") from e

        self._stop.clear()
        assert self._proc.stdout is not None
        self._read_thread = threading.Thread(target=self._read_loop, daemon=True, name="mcp-read")
        self._read_thread.start()
        # stderr thread: capture server logs for debugging
        if self._proc.stderr is not None:
            self._stderr_thread = threading.Thread(target=self._stderr_loop, daemon=True, name="mcp-stderr")
            self._stderr_thread.start()

    def _do_initialize(self) -> None:
        """Run the initialize handshake."""
        assert self._proc is not None
        resp = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "pulse", "version": __version__},
            },
        )
        if "error" in resp:
            raise MCPError(f"initialize failed: {resp['error']}")
        self.server_info = resp.get("result", {}).get("serverInfo", {})
        self._request("notifications/initialized", notification=True)

    def _start_health_thread(self) -> None:
        """Start a background health-check polling thread."""
        if self._health_thread and self._health_thread.is_alive():
            return
        self._health_thread = threading.Thread(target=self._health_loop, daemon=True, name="mcp-health")
        self._health_thread.start()

    def _health_loop(self) -> None:
        """Periodically check if the server is still responsive."""
        while not self._stop.is_set():
            self._stop.wait(timeout=self.health_check_interval)
            if self._stop.is_set():
                break
            if not self.is_alive():
                logger.warning("MCP server '%s' is no longer alive", self.command)
                self._consecutive_failures += 1
                if self._consecutive_failures >= 3:
                    logger.error("MCP server '%s' crashed, attempting reconnect...", self.command)
                    try:
                        self._relaunch()
                    except MCPError as e:
                        logger.error("MCP reconnect failed: %s", e)
                        break
            else:
                self._consecutive_failures = 0

    def _relaunch(self) -> None:
        """Kill the existing process and start a new one (preserving req state)."""
        self._cleanup_proc()
        self._launch()
        self._do_initialize()
        self._consecutive_failures = 0

    def _cleanup_proc(self) -> None:
        """Terminate the current subprocess (if any) without raising."""
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        except Exception:
            logger.exception("exception suppressed")
            pass
            pass
        finally:
            self._proc = None

    def _read_loop(self) -> None:
        """Continuously read JSON-RPC responses from stdout into ``_responses``."""
        if self._proc is None or self._proc.stdout is None:
            raise MCPError("MCP server process is not running")
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

    def _stderr_loop(self) -> None:
        """Read stderr from the server and store in ring buffer for debugging."""
        if self._proc is None or self._proc.stderr is None:
            raise MCPError("MCP server process is not running")
        for line in self._proc.stderr:
            self._stderr_buffer.append(line.strip())

    def _request(self, method: str, params: Any = None, *, notification: bool = False) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for the matching response.

        If the server is dead, attempts a single reconnect transparently.
        """
        if self._proc is None or self._proc.stdin is None:
            # Attempt reconnect
            try:
                self._relaunch()
            except MCPError:
                raise MCPError("MCP client is not started and reconnect failed")
        with self._lock:
            self._req_id += 1
            rid = self._req_id
            req: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
            if not notification:
                req["id"] = rid
            if params is not None:
                req["params"] = params
            try:
                if self._proc is None or self._proc.stdin is None:
                    raise MCPError("MCP server process is not running")
                self._proc.stdin.write(json.dumps(req) + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError):
                # Server died mid-request — try to relaunch
                try:
                    self._relaunch()
                    if self._proc is None or self._proc.stdin is None:
                        raise MCPError("MCP server process is not running")
                    self._proc.stdin.write(json.dumps(req) + "\n")
                    self._proc.stdin.flush()
                except Exception as e:
                    raise MCPError(f"MCP request failed after reconnect: {e}")

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

    def get_stderr(self) -> list[str]:
        """Return captured stderr lines from the server (for diagnostics)."""
        return list(self._stderr_buffer)

    def stop(self) -> None:
        """Terminate the server subprocess and join the reader thread."""
        self._stop.set()
        self._cleanup_proc()
        if self._read_thread and self._read_thread.is_alive():
            self._read_thread.join(timeout=3)
        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=2)

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
        if self._manager is None:
            raise MCPError("MCPTool: no client or manager available")
        return self._manager.ensure_connected(self._server_name)

    def run(self, **kwargs: Any) -> ToolResult:
        """Invoke the MCP tool, with validation + error handling."""
        schema = self._spec.get("inputSchema")
        if schema:
            err = validate_tool_args(schema, kwargs)
            if err:
                return ToolResult(ok=False, error=err)
        try:
            client = self._resolve_client()
            raw = client.call_tool(self._server_tool_name, kwargs)
            if raw.get("isError"):
                text_parts = [c.get("text", "") for c in raw.get("content", [])]
                return ToolResult(ok=False, error=" ".join(text_parts) or "MCP error")
            text_parts = [c.get("text", "") for c in raw.get("content", [])]
            return ToolResult(ok=True, output=" ".join(text_parts))
        except MCPError as e:
            return ToolResult(ok=False, error=str(e))
        except Exception as e:  # noqa: BLE001
            return ToolResult(ok=False, error=f"MCP tool error: {e}")


class MCPManager:
    """Manages one or more MCP server connections."""

    def __init__(self, tool_registry: Any) -> None:
        self._registry = tool_registry
        self._configs: dict[str, Any] = {}
        self._clients: dict[str, MCPClient] = {}
        self._specs: dict[str, list[dict[str, Any]]] = {}
        self._errors: dict[str, str] = {}

    def load_servers(self, server_configs: list[Any]) -> int:
        """Load and discover tools from multiple MCP servers (in parallel).

        Discovery is done once at startup; servers are connected lazily on demand.
        Returns the total number of tools discovered across all servers.
        Skips servers where ``enabled`` is False.
        """
        from concurrent.futures import ThreadPoolExecutor

        for cfg in server_configs:
            self._configs[cfg.name] = cfg

        # Filter to only enabled configs for discovery
        enabled_configs = [c for c in server_configs if c.enabled]
        if not enabled_configs:
            return 0

        def _discover(cfg):
            try:
                client = MCPClient(command=cfg.command, args=list(cfg.args or []))
                client.start()
                specs = client.list_tools()
                client.stop()
                return cfg.name, specs, None
            except Exception as e:
                return cfg.name, [], str(e)

        total = 0
        with ThreadPoolExecutor(max_workers=len(enabled_configs) or 1) as ex:
            futures = [ex.submit(_discover, cfg) for cfg in enabled_configs]
            for fut in futures:
                name, specs, err = fut.result()
                if err:
                    self._errors[name] = str(err)
                    logger.warning("MCP server '%s' failed discovery: %s", name, err)
                else:
                    self._specs[name] = specs
                    for spec in specs:
                        tool = MCPTool(
                            client=None,
                            spec=spec,
                            server_name=name,
                            manager=self,
                        )
                        # Prefix tool name with server name for registry
                        tool.name = f"{name}__{tool.name}"
                        self._registry.register(tool)
                        total += 1
        return total

    def ensure_connected(self, server_name: str) -> MCPClient:
        """Return a connected client for ``server_name``, launching if needed.

        If the server is already connected and alive, returns it. Otherwise,
        relaunches the subprocess.
        """
        client = self._clients.get(server_name)
        if client is not None and client.is_alive():
            return client
        return self.reconnect(server_name)

    def reconnect(self, server_name: str) -> MCPClient:
        """Force-drop any cached client and reconnect fresh."""
        old = self._clients.pop(server_name, None)
        if old:
            try:
                old.stop()
            except Exception:
                logger.exception("exception suppressed")
                pass
                pass
        cfg = self._configs[server_name]
        client = MCPClient(command=cfg.command, args=list(cfg.args or []))
        client.start()
        self._clients[server_name] = client
        return client

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
            try:
                client.stop()
            except Exception:
                logger.exception("exception suppressed")
                pass
                pass
        self._clients.clear()
