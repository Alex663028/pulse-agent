"""Tests for orchestrator/subagent.py — SubagentPool, decompose, merge_results."""
from __future__ import annotations

from unittest.mock import MagicMock


from pulse.llm.provider import LLMResponse, ToolCall, Usage

# Sentinel empty list for tool_calls (LLMResponse.has_tool_calls does len())
from pulse.orchestrator.subagent import (
    RecursionContext,
    SubagentPool,
    SubagentResult,
    SubagentTask,
    decompose,
    merge_results,
)


class TestSubagentTask:
    """Test SubagentTask dataclass."""

    def test_defaults(self):
        """SubagentTask has sensible defaults."""
        task = SubagentTask(id="t1", description="do something")
        assert task.role == "builder"
        assert task.timeout == 60.0
        assert task.max_tokens == 4096
        assert task.context == ""

    def test_custom(self):
        """SubagentTask accepts custom values."""
        task = SubagentTask(
            id="t2", description="review", role="reviewer", timeout=30.0, max_tokens=2048, context="extra"
        )
        assert task.role == "reviewer"
        assert task.timeout == 30.0
        assert task.max_tokens == 2048
        assert task.context == "extra"


class TestSubagentResult:
    """Test SubagentResult dataclass."""

    def test_defaults(self):
        """SubagentResult has sensible defaults."""
        result = SubagentResult(task_id="t1", success=True)
        assert result.answer == ""
        assert result.tokens == 0
        assert result.elapsed == 0.0
        assert result.error is None

    def test_with_data(self):
        """SubagentResult stores data correctly."""
        result = SubagentResult(
            task_id="t1", success=True, answer="done", tokens=100, elapsed=1.5
        )
        assert result.answer == "done"
        assert result.tokens == 100


class TestSubagentPool:
    """Test SubagentPool."""

    def test_init(self):
        """SubagentPool initialization."""
        pool = SubagentPool(max_workers=3)
        assert pool.max_workers == 3

    def test_default_workers(self):
        """SubagentPool default max_workers."""
        pool = SubagentPool()
        assert pool.max_workers == 5

    def test_run_single_task_success(self):
        """Pool runs a single task successfully."""
        pool = SubagentPool(max_workers=1)
        task = SubagentTask(id="t1", description="say hello")
        mock_llm = MagicMock()
        usage = Usage(prompt_tokens=10, completion_tokens=5)
        mock_llm.chat.return_value = LLMResponse(
            content="hello world",
            tool_calls=[],
            model="test",
            usage=usage,
            finish_reason="stop",
        )
        results = pool.run([task], primary=mock_llm)
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].task_id == "t1"

    def test_run_multiple_tasks_parallel(self):
        """Pool runs multiple tasks."""
        pool = SubagentPool(max_workers=2)
        tasks = [
            SubagentTask(id=f"t{i}", description=f"task {i}", timeout=5.0)
            for i in range(3)
        ]
        mock_llm = MagicMock()
        usage = Usage(prompt_tokens=10, completion_tokens=5)
        mock_llm.chat.return_value = LLMResponse(
            content="done", tool_calls=[], model="test", usage=usage, finish_reason="stop"
        )
        results = pool.run(tasks, primary=mock_llm)
        assert len(results) == 3

    def test_run_with_tool_calls(self):
        """Pool handles tool calls in legacy mode."""
        pool = SubagentPool(max_workers=1)
        task = SubagentTask(id="t1", description="use tool")
        mock_llm = MagicMock()
        usage = Usage(prompt_tokens=10, completion_tokens=5)
        # First call returns tool call, second returns final answer
        mock_llm.chat.side_effect = [
            LLMResponse(
                content="using tool",
                tool_calls=[ToolCall(id="tc1", name="echo", arguments={"text": "hi"})],
                model="test",
                usage=usage,
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="done",
                tool_calls=[],
                model="test",
                usage=usage,
                finish_reason="stop",
            ),
        ]
        mock_tools = MagicMock()
        mock_tools.schemas.return_value = [{"function": {"name": "echo"}}]
        mock_tools.call.return_value = MagicMock(ok=True, output="echo hi")
        results = pool.run([task], primary=mock_llm, tools=mock_tools)
        assert len(results) == 1
        assert results[0].success is True

    def test_run_error_isolation(self):
        """Pool isolates errors between tasks."""
        pool = SubagentPool(max_workers=2)
        tasks = [
            SubagentTask(id="t1", description="good task"),
            SubagentTask(id="t2", description="bad task"),
        ]
        mock_llm = MagicMock()
        usage = Usage(prompt_tokens=10, completion_tokens=5)
        # First call success, second call raises
        mock_llm.chat.side_effect = [
            LLMResponse(content="ok", tool_calls=[], model="test", usage=usage, finish_reason="stop"),
            ValueError("LLM failed"),
        ]
        results = pool.run(tasks, primary=mock_llm)
        assert len(results) == 2
        # One should succeed, one should fail
        successes = [r for r in results if r.success]
        failures = [r for r in results if not r.success]
        assert len(successes) + len(failures) == 2

    def test_run_with_recursive_context(self):
        """Pool runs with recursion context when router and tools provided."""
        pool = SubagentPool(max_workers=1)
        task = SubagentTask(id="t1", description="recursive task")
        mock_llm = MagicMock()
        mock_router = MagicMock()
        usage = Usage(prompt_tokens=10, completion_tokens=5)
        mock_router.chat.return_value = LLMResponse(
            content="done", tool_calls=[], model="test", usage=usage, finish_reason="stop"
        )
        mock_tools = MagicMock()
        mock_tools.schemas.return_value = []
        ctx = RecursionContext(router=mock_router, tools=mock_tools, max_iterations=2)
        results = pool.run([task], primary=mock_llm, tools=mock_tools, recursive=ctx)
        assert len(results) == 1
        assert results[0].success is True


class TestDecompose:
    """Test decompose function."""

    def test_decompose_no_llm_fallback(self):
        """decompose with no LLM returns task as-is if no pattern."""
        result = decompose("just do this")
        assert result == ["just do this"]

    def test_decompose_bullet_list(self):
        """decompose extracts bullet list items."""
        task = "- step one\n- step two\n- step three"
        result = decompose(task)
        assert len(result) == 3
        assert "step one" in result[0]

    def test_decompose_numbered_list(self):
        """decompose extracts numbered items."""
        task = "1. collect data 2. analyze trends 3. write report"
        result = decompose(task)
        assert len(result) == 3

    def test_decompose_comma_split(self):
        """decompose splits on comma separators."""
        task = "collect data, analyze trends, write report"
        result = decompose(task)
        assert len(result) == 3

    def test_decompose_with_llm(self):
        """decompose uses LLM for complex task."""
        mock_llm = MagicMock()
        mock_llm.chat.return_value = LLMResponse(
            content="- do A\n- do B\n- do C",
            tool_calls=[],
            model="test",
            usage=Usage(prompt_tokens=10, completion_tokens=5),
            finish_reason="stop",
        )
        result = decompose("complex task", llm=mock_llm)
        assert len(result) == 3

    def test_decompose_limits_to_five(self):
        """decompose caps sub-tasks at 5."""
        task = "- a\n- b\n- c\n- d\n- e\n- f"
        result = decompose(task)
        assert len(result) <= 5


class TestMergeResults:
    """Test merge_results function."""

    def test_merge_small_results_no_llm(self):
        """merge_results returns raw merge for small content."""
        results = [
            SubagentResult(task_id="t1", success=True, answer="part A"),
            SubagentResult(task_id="t2", success=True, answer="part B"),
        ]
        merged = merge_results("task", results, llm=None)
        assert "part A" in merged
        assert "part B" in merged

    def test_merge_successful_results(self):
        """merge_results merges successful results."""
        results = [
            SubagentResult(task_id="t1", success=True, answer="answer A"),
            SubagentResult(task_id="t2", success=True, answer="answer B"),
        ]
        merged = merge_results("task", results, llm=None)
        assert "answer A" in merged
        assert "answer B" in merged

    def test_merge_failed_results(self):
        """merge_results includes error message for failed tasks."""
        results = [
            SubagentResult(task_id="t1", success=False, error="failed"),
        ]
        merged = merge_results("task", results, llm=None)
        assert "failed" in merged

    def test_merge_with_llm(self):
        """merge_results calls LLM for large results."""
        mock_llm = MagicMock()
        mock_llm.chat.return_value = LLMResponse(
            content="Synthesized answer",
            tool_calls=[],
            model="test",
            usage=Usage(prompt_tokens=10, completion_tokens=5),
            finish_reason="stop",
        )
        # Generate results > 200 chars
        results = [
            SubagentResult(task_id=f"t{i}", success=True, answer="x" * 100)
            for i in range(5)
        ]
        merged = merge_results("original task", results, llm=mock_llm)
        assert "Synthesized answer" in merged
