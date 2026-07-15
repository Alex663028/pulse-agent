"""Dynamic tool loader — load tools from YAML/JSON config files.

This module enables third-party extensibility: drop a .yaml or .json file
into ``~/.pulse/tools/`` and Pulse automatically loads it as a tool.

Tool spec format (YAML):
    name: send_email
    description: Send an email via SMTP
    parameters:
      type: object
      properties:
        to: {type: string, description: Recipient address}
        subject: {type: string}
        body: {type: string}
      required: [to, subject]
    command: "sendmail {to} -s '{subject}'"
    timeout: 30

Python script format:
    Create a .py file with a `run(**kwargs) -> str` function.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from pulse.tools.base import Tool, ToolResult

CUSTOM_TOOLS_DIR = Path.home() / ".pulse" / "tools"


@dataclass
class ToolSpec:
    """Definition of a custom tool loaded from config."""
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    command: str | None = None
    script: str | None = None
    timeout: int = 10

    def to_tool(self) -> Tool:
        """Instantiate a Tool from this spec."""
        if self.script:
            return ScriptTool(self)
        return ShellTool(self)


class ShellTool(Tool):
    """Tool backed by a shell command template.

    Placeholders like ``{arg_name}`` are replaced with user-supplied arguments.
    """

    name = "shell-tool"
    description = ""
    parameters: dict[str, Any] = {}

    def __init__(self, spec: ToolSpec):
        self.name = spec.name
        self.description = spec.description
        self.parameters = spec.parameters
        self._command_template = spec.command or ""
        self._timeout = spec.timeout

    def run(self, **kwargs: Any) -> ToolResult:
        """Fill the command template and execute it."""
        if not self._command_template:
            return ToolResult(ok=False, error="no command template defined")
        try:
            cmd = self._command_template.format(**kwargs)
        except KeyError as ke:
            return ToolResult(ok=False, error=f"missing argument: {ke}")
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            output = result.stdout.strip()
            if result.returncode != 0:
                return ToolResult(ok=False, error=f"exit {result.returncode}: {output or result.stderr.strip()}")
            return ToolResult(ok=True, output=output or "(no output)")
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, error=f"timeout after {self._timeout}s")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ScriptTool(Tool):
    """Tool backed by a Python script with a `run(**kwargs) -> str` function."""

    def __init__(self, spec: ToolSpec):
        self.name = spec.name
        self.description = spec.description
        self.parameters = spec.parameters
        self._script_path = spec.script
        self._timeout = spec.timeout

    def run(self, **kwargs: Any) -> ToolResult:
        """Execute the script with JSON-encoded arguments on stdin."""
        if not self._script_path or not Path(self._script_path).exists():
            return ToolResult(ok=False, error=f"script not found: {self._script_path}")
        try:
            result = subprocess.run(
                [sys.executable, "-c", self._build_wrapper(), "run"],
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
            if result.returncode != 0:
                return ToolResult(ok=False, error=f"exit {result.returncode}: {result.stderr.strip()}")
            output = result.stdout.strip()
            return ToolResult(ok=True, output=output or "(no output)")
        except subprocess.TimeoutExpired:
            return ToolResult(ok=False, error=f"timeout after {self._timeout}s")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

    def _build_wrapper(self) -> str:
        """Build a Python script that imports the target module and calls run()."""
        script = Path(self._script_path).read_text(encoding="utf-8")
        # Inject: read JSON args from env, call run(), print result
        wrapper = f"""
import json
import sys
from pathlib import Path

{script}

if __name__ == "__main__":
    args = json.loads('''{json.dumps(dict())}''')
    try:
        result = run(**args)
        print(result)
    except Exception as e:
        print(f"ERROR: {{e}}", file=sys.stderr)
        sys.exit(1)
"""
        return wrapper


def load_custom_tools() -> list[Tool]:
    """Scan the custom tools directory and return all discovered tools."""
    tools: list[Tool] = []
    if not CUSTOM_TOOLS_DIR.exists():
        return tools
    for entry in sorted(CUSTOM_TOOLS_DIR.iterdir()):
        if entry.suffix in (".yaml", ".yml"):
            spec = _load_yaml_spec(entry)
            if spec:
                try:
                    tools.append(spec.to_tool())
                except Exception as e:
                    print(f"[tools] failed to load {entry.name}: {e}")
        elif entry.suffix == ".json":
            spec = _load_json_spec(entry)
            if spec:
                try:
                    tools.append(spec.to_tool())
                except Exception as e:
                    print(f"[tools] failed to load {entry.name}: {e}")
        elif entry.suffix == ".py":
            spec = _load_py_spec(entry)
            if spec:
                try:
                    tools.append(spec.to_tool())
                except Exception as e:
                    print(f"[tools] failed to load {entry.name}: {e}")
    return tools


def _load_yaml_spec(path: Path) -> ToolSpec | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not data or "name" not in data:
            return None
        return ToolSpec(
            name=data["name"],
            description=data.get("description", data["name"]),
            parameters=data.get("parameters", {"type": "object", "properties": {}}),
            command=data.get("command"),
            script=data.get("script"),
            timeout=data.get("timeout", 10),
        )
    except Exception:
        return None


def _load_json_spec(path: Path) -> ToolSpec | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data or "name" not in data:
            return None
        return ToolSpec(
            name=data["name"],
            description=data.get("description", data["name"]),
            parameters=data.get("parameters", {"type": "object", "properties": {}}),
            command=data.get("command"),
            script=data.get("script"),
            timeout=data.get("timeout", 10),
        )
    except Exception:
        return None


def _load_py_spec(path: Path) -> ToolSpec | None:
    """Load a Python file as a script tool."""
    try:
        content = path.read_text(encoding="utf-8")
        # Extract description from first docstring or comment
        desc = path.stem
        if '"""' in content:
            desc = content.split('"""')[1].strip()[:80]
        elif "'''" in content:
            desc = content.split("'''")[1].strip()[:80]
        return ToolSpec(
            name=path.stem.lower().replace("-", "_"),
            description=desc,
            script=str(path),
            parameters={"type": "object", "properties": {}},
            timeout=30,
        )
    except Exception:
        return None


def list_custom_tool_specs() -> list[str]:
    """Return names of all custom tool config files found."""
    if not CUSTOM_TOOLS_DIR.exists():
        return []
    return [e.stem for e in sorted(CUSTOM_TOOLS_DIR.iterdir())
            if e.suffix in (".yaml", ".yml", ".json", ".py")]
