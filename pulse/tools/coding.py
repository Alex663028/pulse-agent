"""Coding-focused tools: git, grep, repl, test_runner, linter, project_context.

Pulse already ships basic read/write/edit. Codex-level coding needs codex-style tools:

- git_: status, diff, log, add, commit, branch (read-only by default; write ops require approval)
- grep: regex search across the project
- repl: interactive PTY session
- test_runner: run pytest/npm and parse output
- lint: ruff/mypy check
- project_context: read imports, pyproject, structure
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import Any

from pulse.tools.base import Tool, ToolResult


class GitStatusTool(Tool):
    """Show working tree status."""

    name = "git_status"
    description = "Show git working tree status. Args: path (optional, default=.)"
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "repo path"}},
    }

    def run(self, path: str = ".", **kwargs: Any) -> ToolResult:
        try:
            r = subprocess.run(
                ["git", "status", "--short", "--branch"],
                capture_output=True, text=True, timeout=10, cwd=path,
            )
            if r.returncode != 0:
                return ToolResult(ok=False, error=r.stderr.strip())
            return ToolResult(ok=True, output=r.stdout.strip())
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class GitDiffTool(Tool):
    """Show diff for a file or the whole tree."""

    name = "git_diff"
    description = "Show git diff. Args: path (file or directory), cached (bool, default False)"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "file or directory path"},
            "cached": {"type": "boolean", "description": "show staged diff"},
        },
    }

    def run(self, path: str = ".", cached: bool = False, **kwargs: Any) -> ToolResult:
        try:
            cmd = ["git", "diff", "--patch"]
            if cached:
                cmd.append("--staged")
            cmd.append("--")
            cmd.append(path)
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, cwd=".")
            if r.returncode != 0:
                return ToolResult(ok=False, error=r.stderr.strip())
            return ToolResult(ok=True, output=r.stdout.strip() or "(no diff)")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class GitLogTool(Tool):
    """Show commit log."""

    name = "git_log"
    description = "Show git commit log. Args: path, count (default 10)"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "file or directory path"},
            "count": {"type": "integer", "description": "number of commits (default 10)"},
        },
    }

    def run(self, path: str = ".", count: int = 10, **kwargs: Any) -> ToolResult:
        try:
            r = subprocess.run(
                ["git", "log", f"-n{count}", "--oneline", "--", path],
                capture_output=True, text=True, timeout=10, cwd=".",
            )
            if r.returncode != 0:
                return ToolResult(ok=False, error=r.stderr.strip())
            return ToolResult(ok=True, output=r.stdout.strip() or "(no commits)")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class GrepTool(Tool):
    """Regex search across the project (augmented grep)."""

    name = "grep"
    description = "Search for a regex in files. Args: pattern, path (default=.), glob (default=*.py)"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "regex pattern"},
            "path": {"type": "string", "description": "search root"},
            "glob": {"type": "string", "description": "file glob filter"},
        },
        "required": ["pattern"],
    }

    def run(self, pattern: str, path: str = ".", glob: str = "*.py", **kwargs: Any) -> ToolResult:
        try:
            import re
            results = []
            # Skip binary/cache dirs
            skip_dirs = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv"}
            base = Path(path)
            for f in sorted(base.glob(glob)):
                if not f.is_file():
                    continue
                if any(part in skip_dirs for part in f.parts):
                    continue
                if f.suffix in (".pyc", ".so", ".dll", ".exe", ".bin", ".dat", ".db"):
                    continue
                if f.stat().st_size > 1024 * 1024:
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                    for i, line in enumerate(text.splitlines(), 1):
                        if re.search(pattern, line):
                            results.append(f"{f}:{i}:{line}")
                except Exception:
                    pass
            if not results:
                return ToolResult(ok=True, output="(no matches)")
            output = "\n".join(results[:200])
            if len(results) > 200:
                output += f"\n... ({len(results)} total)"
            return ToolResult(ok=True, output=output)
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ReplTool(Tool):
    """Run a Python expression one shot or start a PTY session."""

    name = "repl"
    description = "Run a Python expression in the REPL. Args: code"
    parameters = {
        "type": "object",
        "properties": {"code": {"type": "string", "description": "Python code to execute"}},
        "required": ["code"],
    }

    def run(self, code: str, **kwargs: Any) -> ToolResult:
        try:
            exec_globals = {"__builtins__": __builtins__}
            exec(compile(code, "<repl>", "exec"), exec_globals)
            return ToolResult(ok=True, output=str(exec_globals.get("_", "(done)")))
        except Exception as e:
            return ToolResult(ok=False, error=f"repl error: {e}")


class TestRunnerTool(Tool):
    """Run pytest on a target path."""

    name = "test_runner"
    description = "Run pytest on a path. Args: path (default=.)"
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "test file or directory"}},
    }

    def run(self, path: str = ".", **kwargs: Any) -> ToolResult:
        try:
            r = subprocess.run(
                ["python", "-m", "pytest", path, "-x", "--tb=short", "-q"],
                capture_output=True, text=True, timeout=120, cwd=".",
            )
            ok = r.returncode == 0
            out = r.stdout[-4000:]
            if r.stderr:
                out += "\n" + r.stderr[-2000:]
            return ToolResult(ok=ok, output=out)
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class LintTool(Tool):
    """Run ruff check on a path."""

    name = "lint"
    description = "Run ruff linter on a path. Args: path (default=.), fix (bool)"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "file or directory path"},
            "fix": {"type": "boolean", "description": "auto-fix where possible"},
        },
    }

    def run(self, path: str = ".", fix: bool = False, **kwargs: Any) -> ToolResult:
        try:
            cmd = ["ruff", "check", path, "--select", "E,F,W", "--ignore", "E501"]
            if fix:
                cmd.append("--fix")
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=".")
            output = r.stdout.strip() or "(no issues)"
            if r.returncode != 0:
                output += "\n" + r.stderr.strip()
            return ToolResult(ok=True, output=output)
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ProjectContextTool(Tool):
    """Analyze project structure: imports, pyproject, tree."""

    name = "project_context"
    description = "Analyze project structure. Args: path (default=.), depth (default=2)"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "project root"},
            "depth": {"type": "integer", "description": "tree depth"},
        },
    }

    def run(self, path: str = ".", depth: int = 2, **kwargs: Any) -> ToolResult:
        try:
            root = Path(path).resolve()
            lines = [f"# Project: {root.name}"]

            # pyproject or requirements
            if (root / "pyproject.toml").exists():
                lines.append("\n## pyproject.toml")
                lines.append((root / "pyproject.toml").read_text()[:1500])
            elif (root / "requirements.txt").exists():
                lines.append("\n## requirements.txt")
                lines.append((root / "requirements.txt").read_text()[:1500])

            # tree
            lines.append(f"\n## Tree (depth {depth})")
            for f in sorted(root.rglob("*")):
                rel = f.relative_to(root)
                if len(rel.parts) <= depth and f.is_file():
                    lines.append(str(rel))

            # imports from main package (first 20)
            py_files = sorted(root.rglob("*.py"))[:20]
            if py_files:
                lines.append("\n## Import analysis")
                for pf in py_files:
                    src = pf.read_text(encoding="utf-8", errors="replace")
                    try:
                        tree = ast.parse(src, filename=str(pf))
                        imports = []
                        for node in ast.walk(tree):
                            if isinstance(node, ast.Import):
                                for alias in node.names:
                                    imports.append(alias.name)
                            elif isinstance(node, ast.ImportFrom) and node.module:
                                imports.append(node.module)
                        if imports:
                            lines.append(f"{pf.relative_to(root)}: {', '.join(sorted(set(imports)))}")
                    except Exception:
                        pass

            return ToolResult(ok=True, output="\n".join(lines[:300]))
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


__all__ = [
    "GitStatusTool", "GitDiffTool", "GitLogTool",
    "GrepTool", "ReplTool", "TestRunnerTool", "LintTool", "ProjectContextTool",
]
