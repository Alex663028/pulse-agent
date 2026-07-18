"""Tool registry with permission + recovery-aware invocation + filtering."""

from __future__ import annotations

import logging
from typing import Any, Optional, Set

from pulse.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


class ToolRegistry:
    """In-memory registry of available tools, indexed by name.

    Supports tool filtering via allowlist (only these tools) and
    blocklist (never expose these tools to the LLM).
    """

    def __init__(
        self,
        allowlist: Optional[Set[str]] = None,
        blocklist: Optional[Set[str]] = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._allowlist = allowlist  # if set, only these tools are exposed
        self._blocklist = blocklist or set()  # never expose these

    def register(self, tool: Tool) -> None:
        """Register a tool under its ``name`` attribute, overwriting any prior entry."""
        if tool.name in self._blocklist:
            logger.debug("tool '%s' is in blocklist, skipping", tool.name)
            return
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        """Look up a tool by name; returns None if not registered."""
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        """Return OpenAI-compatible function schemas for all registered tools.

        Respects allowlist/blocklist filtering.
        """
        allowed = []
        for name, tool in self._tools.items():
            if self._allowlist and name not in self._allowlist:
                continue
            if name in self._blocklist:
                continue
            allowed.append(tool.to_schema())
        return allowed

    def call(self, name: str, args: dict[str, Any]) -> ToolResult:
        """Invoke the named tool with ``args`` via the recovery layer; never raises."""
        from pulse.orchestrator.recovery import ErrorClass, RecoveryError, guarded

        tool = self._tools.get(name)
        if not tool:
            return ToolResult(ok=False, error=f"unknown tool: {name}")
        try:
            return guarded(tool.run, **args, allow=(ErrorClass.TOOL_FAIL,))
        except RecoveryError as e:
            return ToolResult(ok=False, error=str(e))

    @property
    def tool_names(self) -> list[str]:
        """Return all registered tool names (unfiltered)."""
        return list(self._tools.keys())

    @property
    def allowed_names(self) -> list[str]:
        """Return only the tool names that pass filtering."""
        return [
            n
            for n in self._tools
            if (not self._allowlist or n in self._allowlist)
            and n not in self._blocklist
        ]

    def set_allowlist(self, names: Optional[Set[str]]) -> None:
        """Set/clear the allowlist. None = allow all."""
        self._allowlist = names

    def set_blocklist(self, names: Optional[Set[str]]) -> None:
        """Set/clear the blocklist."""
        self._blocklist = names or set()
