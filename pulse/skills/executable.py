"""Executable skill system — make skills callable, testable, and extensible.

An executable skill extends the agentskills.io frontmatter format with a Python
module interface. Skills can:

1. Declare their own tools via ``get_tools()``
2. Execute programmatically via ``execute(**kwargs)``
3. Self-test via ``test() -> list[str]`` (returns error messages, empty = pass)
4. Be hot-reloaded (filesystem changes detected automatically)

Convention:
    skills/my-skill/
        SKILL.md          # name/description/agentskills frontmatter (unchanged)
        __init__.py       # optional, Python package entry point
        runner.py         # REQUIRED for executable skills — defines the execution logic
        tests.py          # optional test file

    runner.py must export:
        def get_tools() -> list[Tool]: ...
        def execute(**kwargs) -> str: ...
        def test() -> list[str]: ...   (optional)

Third-party devs can drop a skill directory anywhere on ``skills.d`` paths and
it will be auto-discovered by ``SkillRegistry``.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pulse.config.settings import Settings
from pulse.tools.base import Tool
from pulse.tools.registry import ToolRegistry


@runtime_checkable
class SkillRunner(Protocol):
    """Interface a skill's runner module must provide."""

    def get_tools(self) -> list[Tool]: ...

    def execute(self, **kwargs: Any) -> str: ...

    def test(self) -> list[str]: ...


class BaseExecutableSkill(ABC):
    """Base class for executable skills. Provides a sensible default implementation that subclasses override."""

    def get_tools(self) -> list[Tool]:
        """Return tools this skill introduces to the registry."""
        return []

    @abstractmethod
    def execute(self, **kwargs: Any) -> str:
        """Run the skill with the given arguments."""
        raise NotImplementedError

    def test(self) -> list[str]:
        """Run skill-specific tests. Returns list of error messages (empty = pass)."""
        return []


@dataclass
class SkillHandle:
    """Reference to a loaded executable skill. Created by SkillRegistry."""
    name: str
    path: Path
    runner: Any  # module or BaseExecutableSkill instance
    tools: list[Tool] = field(default_factory=list)
    loaded_at: datetime = field(default_factory=datetime.now)
    last_modified: float = 0.0
    errors: list[str] = field(default_factory=list)

    def is_stale(self) -> bool:
        """Return True if the source file has been modified since last load."""
        if not self.path.exists():
            return False
        return self.path.stat().st_mtime > self.last_modified

    def reload(self) -> None:
        """Hot-reload the skill from disk."""
        if self.path.is_dir():
            runner_path = self.path / "runner.py"
        else:
            runner_path = self.path
        if runner_path.exists():
            spec = importlib.util.spec_from_file_location(
                f"skill_{self.name}", str(runner_path)
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                self.runner = mod
                self.last_modified = runner_path.stat().st_mtime
                self.loaded_at = datetime.now()
                self.errors = []
                # Try running tests
                if hasattr(mod, "test"):
                    try:
                        self.errors = mod.test() or []
                    except Exception as e:
                        self.errors = [f"test failure: {e}"]

    def execute(self, **kwargs: Any) -> str:
        """Execute the skill, auto-reloading if stale."""
        if self.is_stale():
            self.reload()
        if hasattr(self.runner, "execute"):
            return self.runner.execute(**kwargs)
        return f"skill '{self.name}' has no execute function"


def load_executable_skills(
    search_paths: list[Path],
    registry: ToolRegistry | None = None,
) -> list[SkillHandle]:
    """Scan directories for skills with a runner.py and load them as executables."""
    handles: list[SkillHandle] = []
    for base in search_paths:
        if not base.exists():
            continue
        for child in sorted(base.iterdir()):
            if child.is_dir():
                runner = child / "runner.py"
                if runner.exists():
                    handle = _load_skill_handle(child.name, child, runner)
                    handles.append(handle)
                    if registry:
                        for tool in handle.tools:
                            registry.register(tool)
            elif child.is_file() and child.suffix == ".py" and child.stem != "__init__":
                handle = _load_skill_handle(child.stem, child, child)
                handles.append(handle)
                if registry:
                    for tool in handle.tools:
                        registry.register(tool)
    return handles


def _load_skill_handle(name: str, path: Path, runner_file: Path) -> SkillHandle:
    """Load a skill handle from a runner.py file."""
    errors: list[str] = []
    tools: list[Tool] = []
    try:
        spec = importlib.util.spec_from_file_location(f"skill_{name}", str(runner_file))
        if spec is None or spec.loader is None:
            return SkillHandle(name=name, path=path, runner=None, errors=["failed to load module"])
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if hasattr(mod, "get_tools"):
            tools = mod.get_tools() or []
        return SkillHandle(
            name=name,
            path=path,
            runner=mod,
            tools=tools,
            last_modified=runner_file.stat().st_mtime,
        )
    except Exception as e:
        return SkillHandle(name=name, path=path, runner=None, errors=[str(e)])


def run_skill_tests(handle: SkillHandle) -> list[str]:
    """Run the test() function of a skill handle, returning errors."""
    if handle.runner is None:
        return ["not loaded"]
    if not hasattr(handle.runner, "test"):
        return []
    try:
        result = handle.runner.test()
        return result or []
    except Exception as e:
        return [f"test exception: {e}"]
