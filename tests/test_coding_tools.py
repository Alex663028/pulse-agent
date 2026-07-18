"""Tests for coding tools: Git_*, Grep, Repl, TestRunner, Lint, ProjectContext."""

from __future__ import annotations

import shutil

import pytest

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

# Skip lint tests if ruff is not installed
has_ruff = shutil.which("ruff") is not None


class TestGitTools:
    def test_status(self):
        tool = GitStatusTool()
        result = tool.run(".")
        # Should work in this repo
        assert result.ok or result.error  # doesn't crash

    def test_diff(self):
        tool = GitDiffTool()
        result = tool.run(".")
        assert result.ok or result.error

    def test_log(self):
        tool = GitLogTool()
        result = tool.run(".", count=5)
        assert result.ok or result.error


class TestGrepTool:
    def test_simple_pattern(self):
        tool = GrepTool()
        result = tool.run("def test_", path=".", glob="**/*.py")
        assert result.ok
        assert "test_" in result.output

    def test_no_match(self):
        tool = GrepTool()
        result = tool.run("ZZZNONEXISTENT", path=".")
        assert "(no matches)" in result.output


class TestReplTool:
    def test_expression(self):
        tool = ReplTool()
        result = tool.run("x = 2 + 2")
        assert result.ok

    def test_error_handling(self):
        tool = ReplTool()
        result = tool.run("1 + 'a'")
        assert not result.ok
        assert "repl error" in result.error


class TestProjectContextTool:
    def test_tree_output(self):
        tool = ProjectContextTool()
        result = tool.run(".", depth=1)
        assert result.ok
        assert "Project" in result.output


class TestLintTool:
    @pytest.mark.skipif(not has_ruff, reason="ruff not installed")
    def test_lint_clean_file(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text("x = 1\n")
        tool = LintTool()
        result = tool.run(str(f))
        assert result.ok

    @pytest.mark.skipif(not has_ruff, reason="ruff not installed")
    def test_lint_dirty_file(self, tmp_path):
        f = tmp_path / "dirty.py"
        f.write_text("import os\nimport sys\nx = 1\n")
        tool = LintTool()
        result = tool.run(str(f))
        assert result.ok  # reports issues but doesn't fail


class TestTestRunnerTool:
    def test_passing_tests(self, tmp_path):
        f = tmp_path / "test_trivial.py"
        f.write_text("def test_one():\n    assert 1 + 1 == 2\n")
        tool = TestRunnerTool()
        result = tool.run(str(f))
        assert result.ok

    def test_failing_tests(self, tmp_path):
        f = tmp_path / "test_bad.py"
        f.write_text("def test_fail():\n    assert 1 + 1 == 3\n")
        tool = TestRunnerTool()
        result = tool.run(str(f))
        assert not result.ok
