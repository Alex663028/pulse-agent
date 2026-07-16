"""Error recovery — the core reliability layer.

Hermes' weakness: a single transient failure or an over-long context can blow
up a whole run. Pulse classifies every error and applies a targeted policy:

  TRANSIENT     (network/rate-limit/5xx)  -> exponential backoff + jitter retry
  TOOL_FAIL     (a tool raised)           -> isolated retry with a fresh prompt
  CTX_OVERFLOW  (token budget exceeded)   -> compact older turns, retry
  LLM_REFUSE    (model declined)          -> route to auxiliary model / ask user
  UNKNOWN                                  -> surface immediately, fail safe

Retries are bounded and deterministic-friendly (the sleep is injectable).
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

from pulse.llm.provider import LLMError, AnthropicError

T = TypeVar("T")


class ErrorClass:
    """Sentinel string constants for classified error categories."""

    TRANSIENT = "TRANSIENT"
    TOOL_FAIL = "TOOL_FAIL"
    CTX_OVERFLOW = "CTX_OVERFLOW"
    LLM_REFUSE = "LLM_REFUSE"
    UNKNOWN = "UNKNOWN"


class RecoveryError(Exception):
    """Raised when recovery exhausts its retries."""


class CtxOverflowError(Exception):
    """Signal that the context budget was exceeded."""


def classify(exc: Exception) -> str:
    """Classify an exception into one of the ``ErrorClass`` categories for recovery routing."""
    if isinstance(exc, CtxOverflowError):
        return ErrorClass.CTX_OVERFLOW
    if isinstance(exc, (LLMError, AnthropicError)):
        msg = str(exc).lower()
        if any(k in msg for k in ("rate", "429", "timeout", "timed out", "connection", "503", "502", "500")):
            return ErrorClass.TRANSIENT
        if any(k in msg for k in ("refuse", "decline", "cannot fulfill", "i can't", "i cannot")):
            return ErrorClass.LLM_REFUSE
        return ErrorClass.UNKNOWN
    if isinstance(exc, (ValueError, KeyError, RuntimeError)):
        return ErrorClass.TOOL_FAIL
    return ErrorClass.UNKNOWN


@dataclass
class RetryPolicy:
    """Retry bounds for the ``guarded`` wrapper: attempts, base delay, jitter, and injectable sleep."""

    max_attempts: int = 4
    base_delay: float = 0.2
    jitter: float = 0.1
    sleep: Callable[[float], None] = lambda s: time.sleep(s)


def _jitter(jitter: float) -> float:
    return secrets.randbelow(int(jitter * 1000)) / 1000.0


def guarded(fn: Callable[..., T], *args, policy: RetryPolicy | None = None, allow: tuple[str, ...] = (ErrorClass.TRANSIENT,), on_tool_fail: Callable[[], None] | None = None, **kwargs) -> T:
    """Run ``fn`` with bounded retry. Only error classes in ``allow`` are
    retried; everything else fails fast (fail-safe).

    Programming errors (AttributeError, TypeError, NameError) are re-raised
    immediately — they indicate bugs, not transient failures.
    """
    policy = policy or RetryPolicy()
    # These errors signal code bugs, not recoverable failures; surface immediately
    _programming_errors = (AttributeError, TypeError, NameError, SyntaxError, ImportError)
    last: Exception | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except _programming_errors:
            raise  # don't wrap or retry — these are bugs
        except Exception as e:  # noqa: BLE001
            cls = classify(e)
            last = e
            if cls == ErrorClass.CTX_OVERFLOW:
                raise  # handled by the orchestrator's compaction path
            if cls == ErrorClass.TOOL_FAIL and on_tool_fail:
                on_tool_fail()
            if cls in allow and attempt < policy.max_attempts:
                delay = policy.base_delay * (2 ** (attempt - 1)) + _jitter(policy.jitter)
                policy.sleep(delay)
                continue
            raise RecoveryError(f"[{cls}] {e}") from e
    if last is None:
        raise RecoveryError("exhausted retries with no recorded failure")
    raise RecoveryError(f"exhausted retries: {last}")
