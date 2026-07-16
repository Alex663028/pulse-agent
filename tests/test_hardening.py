"""Regression tests for P0/P1 hardening in pulse."""
from __future__ import annotations

import secrets
from pathlib import Path


def test_jitter_uses_secrets(monkeypatch):
    """_jitter should call secrets.randbelow, not random.uniform."""
    import pulse.orchestrator.recovery as rec

    calls: list[tuple[int, int]] = []

    def fake_randbelow(n: int) -> int:
        calls.append((n,))
        return 0

    monkeypatch.setattr(secrets, "randbelow", fake_randbelow)
    value = rec._jitter(0.5)
    assert value == 0.0
    assert len(calls) == 1
    # jitter=0.5 -> randbelow(500)
    assert calls[0] == (500,)


def test_shell_tool_rejects_empty_command():
    """ShellExecTool.run('') should fail fast."""
    from pulse.tools.core import ShellExecTool

    tool = ShellExecTool.__new__(ShellExecTool)
    tool.name = "shell_exec"
    tool.description = ""
    tool.parameters = {}
    result = tool.run(command="")
    assert result.ok is False
    assert "empty" in result.error.lower()


def test_web_dependency_error_raised():
    """DependencyError should be importable from pulse.web.server."""
    from pulse.web.server import DependencyError

    assert issubclass(DependencyError, RuntimeError)


def test_recovery_no_last_after_exhaustion():
    """guarded should raise RecoveryError without hitting assert."""
    from pulse.orchestrator.recovery import RecoveryError, RetryPolicy, guarded

    def always_fail():
        raise ValueError("boom")

    policy = RetryPolicy(max_attempts=1, base_delay=0.0, jitter=0.0, sleep=lambda s: None)
    try:
        guarded(always_fail, policy=policy)
    except RecoveryError as exc:
        # single-attempt raises immediately, not via exhausted path
        assert "[TOOL_FAIL]" in str(exc)
    else:
        raise AssertionError("expected RecoveryError")


def test_recovery_exhausted_retries():
    """After exhausting retries, guarded should raise RecoveryError."""
    from pulse.orchestrator.recovery import ErrorClass, RecoveryError, RetryPolicy, guarded

    def always_fail():
        raise ValueError("boom")

    policy = RetryPolicy(max_attempts=2, base_delay=0.0, jitter=0.0, sleep=lambda s: None)

    # Patch classify to TRANSIENT so guarded retries until exhaustion
    import pulse.orchestrator.recovery as rec

    original_classify = rec.classify

    def fake_classify(exc):
        return ErrorClass.TRANSIENT

    rec.classify = fake_classify
    try:
        guarded(always_fail, policy=policy)
    except RecoveryError as exc:
        # On exhaustion, guarded wraps the last failure in RecoveryError
        assert "boom" in str(exc)
    else:
        raise AssertionError("expected RecoveryError")
    finally:
        rec.classify = original_classify


def test_open_uses_context_manager():
    """Verify cli/main.py uses with open() for cron loading."""
    source = (
        Path(__file__).resolve().parents[1]
        .joinpath("pulse/cli/main.py")
        .read_text(encoding="utf-8")
    )
    assert "json.loads(open(" not in source
    assert 'with open(' in source
