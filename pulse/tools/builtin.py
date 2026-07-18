"""Register all built-in tools (core + original three)."""

from __future__ import annotations

from pulse.tools.base import CalcTool, ListDirTool, ReadFileTool
from pulse.tools.core import (
    EditFileTool,
    HttpClientTool,
    PythonExecTool,
    ShellExecTool,
    WebFetchTool,
    WebSearchTool,
    WriteFileTool,
)
from pulse.tools.registry import ToolRegistry

__all__ = ["register_builtin_tools"]

ALL_BUILTIN_TOOLS = [
    # Original
    ReadFileTool(),
    ListDirTool(),
    CalcTool(),
    # New
    WriteFileTool(),
    EditFileTool(),
    WebSearchTool(),
    WebFetchTool(),
    PythonExecTool(),
    ShellExecTool(),
    HttpClientTool(),
]


def register_builtin_tools(registry: ToolRegistry) -> None:
    """Register every built-in tool on the given registry."""
    for t in ALL_BUILTIN_TOOLS:
        registry.register(t)


def list_builtin_tool_names() -> list[str]:
    """Return names of all registered built-in tools."""
    return [t.name for t in ALL_BUILTIN_TOOLS]


def get_builtin_tool(name: str):
    """Return a single built-in tool by name, or None."""
    for t in ALL_BUILTIN_TOOLS:
        if t.name == name:
            return t
    return None
