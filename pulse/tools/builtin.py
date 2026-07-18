"""Register all built-in tools (core + coding + original three)."""

from __future__ import annotations

from pulse.tools.base import CalcTool, ListDirTool, ReadFileTool
from pulse.tools.coding import (
    GitDiffTool,
    GitLogTool,
    GitStatusTool,
    GrepTool,
    LintTool,
    ProjectContextTool,
    ReplTool,
    TestRunnerTool,
)
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
    # File operations
    WriteFileTool(),
    EditFileTool(),
    # Coding
    GitStatusTool(),
    GitDiffTool(),
    GitLogTool(),
    GrepTool(),
    ReplTool(),
    TestRunnerTool(),
    LintTool(),
    ProjectContextTool(),
    # Web
    WebSearchTool(),
    WebFetchTool(),
    # Execution
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
