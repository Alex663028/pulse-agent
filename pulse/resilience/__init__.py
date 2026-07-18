"""Resilience primitives: circuit breaker, retry with exponential backoff, async wrapper."""

from __future__ import annotations

import asyncio
import enum
import functools
import logging
import time
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(enum.Enum):
    CLOSED = "closed"  # normal operation
    OPEN = "open"  # failing, reject fast
    HALF_OPEN = "half_open"  # testing if recovered


class CircuitBreakerError(Exception):
    """Raised when the circuit breaker is open."""

    pass


class CircuitBreaker:
    """Thread-safe circuit breaker for external calls.

    States:
        CLOSED   → calls pass through, failures counted
        OPEN     → calls rejected immediately after failure_threshold
        HALF_OPEN → trial call allowed; success → CLOSED, failure → OPEN
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        expected_exceptions: tuple[type[Exception], ...] = (Exception,),
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exceptions = expected_exceptions
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._lock = asyncio.Lock() if asyncio.get_event_loop().is_running() else None
        import threading

        self._thread_lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def _sync_allows(self) -> bool:
        with self._thread_lock:
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    return True
                return False
            # HALF_OPEN: allow one trial
            return True

    def call(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        if not self._sync_allows():
            raise CircuitBreakerError(
                f"circuit breaker '{self.name}' is open ({self._failure_count} failures)"
            )
        try:
            result = fn(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exceptions as e:
            self._on_failure(e)
            raise

    async def acall(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        if not self._sync_allows():
            raise CircuitBreakerError(
                f"circuit breaker '{self.name}' is open ({self._failure_count} failures)"
            )
        try:
            if asyncio.iscoroutinefunction(fn):
                result = await fn(*args, **kwargs)
            else:
                result = fn(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exceptions as e:
            self._on_failure(e)
            raise

    def _on_success(self) -> None:
        with self._thread_lock:
            self._failure_count = 0
            self._state = CircuitState.CLOSED

    def _on_failure(self, exc: Exception) -> None:
        with self._thread_lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "circuit breaker '%s' OPEN after %d failures",
                    self.name,
                    self._failure_count,
                )


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable:
    """Decorator for retry with exponential backoff."""

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Optional[Exception] = None
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_attempts - 1:
                        wait = delay * (backoff**attempt)
                        logger.debug(
                            "retry %s attempt %d/%d in %.1fs: %s",
                            fn.__name__,
                            attempt + 1,
                            max_attempts,
                            wait,
                            e,
                        )
                        time.sleep(wait)
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator


__all__ = ["CircuitBreaker", "CircuitBreakerError", "CircuitState", "retry"]
