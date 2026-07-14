"""Tool registry with permission + recovery-aware invocation."""
from __future__ import annotations

from typing import Any, Optional

from pulse.tools.base import Tool, ToolResult


class ToolRegistry:
    """In-memory registry of available tools, indexed by name."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool under its ``name`` attribute, overwriting any prior entry."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        """Look up a tool by name; returns None if not registered."""
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        """Return OpenAI-compatible function schemas for all registered tools."""
        return [t.to_schema() for t in self._tools.values()]

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
