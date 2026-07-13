"""Register the built-in toolset."""
from __future__ import annotations

from pulse.tools.base import CalcTool, ListDirTool, ReadFileTool
from pulse.tools.registry import ToolRegistry


def register_builtin_tools(registry: ToolRegistry) -> None:
    for t in (ReadFileTool(), ListDirTool(), CalcTool()):
        registry.register(t)
