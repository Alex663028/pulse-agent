"""Tool abstraction.

A ``Tool`` declares a JSON-schema parameter spec (so it can be offered to any
OpenAI-compatible model) and a ``run`` method. Tool calls are wrapped by the
orchestrator's recovery layer, so a failing tool is isolated and retried
rather than aborting the whole task.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolResult:
    """Outcome of a single tool invocation, carrying success flag, output and optional error."""

    ok: bool
    output: str = ""
    error: Optional[str] = None


class Tool(ABC):
    """Abstract base for all agent-callable tools."""

    name: str = "tool"
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)

    @abstractmethod
    def run(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given keyword arguments and return a ToolResult."""

    def to_schema(self) -> dict[str, Any]:
        """Render this tool as an OpenAI-compatible function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}},
            },
        }


@dataclass
class ReadFileTool(Tool):
    """Built-in tool that reads a UTF-8 text file from the local filesystem."""

    name = "read_file"
    description = "Read a text file from the local filesystem. Args: path."
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}

    def run(self, path: str = "", **kwargs: Any) -> ToolResult:
        """Read up to 4000 chars from ``path``; returns ok=False if missing."""
        from pathlib import Path

        p = Path(path)
        if not p.exists():
            return ToolResult(ok=False, error=f"no such file: {path}")
        return ToolResult(ok=True, output=p.read_text(encoding="utf-8", errors="replace")[:4000])


@dataclass
class ListDirTool(Tool):
    """Built-in tool that lists the entries of a directory."""

    name = "list_dir"
    description = "List files in a directory. Args: path."
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}

    def run(self, path: str = ".", **kwargs: Any) -> ToolResult:
        """Return a newline-sorted listing of ``path``."""
        from pathlib import Path

        try:
            items = sorted(p.name or "." for p in Path(path).iterdir())
            return ToolResult(ok=True, output="\n".join(items))
        except Exception as e:  # noqa: BLE001
            return ToolResult(ok=False, error=str(e))


@dataclass
class CalcTool(Tool):
    """Built-in tool that safely evaluates a simple arithmetic expression."""

    name = "calc"
    description = "Evaluate a simple arithmetic expression safely. Args: expr."
    parameters = {"type": "object", "properties": {"expr": {"type": "string"}}, "required": ["expr"]}

    def run(self, expr: str = "", **kwargs: Any) -> ToolResult:
        """Evaluate ``expr`` (numbers and + - * / only) via AST, returning the result."""
        import ast
        import operator as op

        ops = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv, ast.USub: op.neg}
        try:
            node = ast.parse(expr, mode="eval").body

            def _ev(n: ast.AST):
                if isinstance(n, ast.Constant):
                    if not isinstance(n.value, (int, float)):
                        raise ValueError("only numbers")
                    return n.value
                if isinstance(n, ast.BinOp) and type(n.op) in ops:
                    return ops[type(n.op)](_ev(n.left), _ev(n.right))
                if isinstance(n, ast.UnaryOp) and type(n.op) in ops:
                    return ops[type(n.op)](_ev(n.operand))
                raise ValueError("unsupported expression")

            return ToolResult(ok=True, output=str(_ev(node)))
        except Exception as e:  # noqa: BLE001
            return ToolResult(ok=False, error=str(e))
