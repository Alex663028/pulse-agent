"""Simple token-bucket rate limiter for LLM API calls.

Prevents burst traffic that triggers 429s.  Each provider can have its own
bucket; if no bucket is configured a global default is used.
"""
from __future__ import annotations

import threading
import time


class TokenBucket:
    """Leaky-bucket rate limiter.

    Parameters
    ----------
    rate : float
        Tokens added per second.
    capacity : int
        Maximum burst size (bucket depth).
    """

    def __init__(self, rate: float = 1.0, capacity: int = 5):
        self.rate = rate
        self.capacity = capacity
        self._tokens: float = capacity  # start full
        self._last: float = time.time()
        self._lock = threading.Lock()

    def acquire(self, tokens: int = 1) -> None:
        """Block until ``tokens`` are available, then consume them."""
        with self._lock:
            now = time.time()
            self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
            self._last = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                return

            # calculate wait time
            deficit = tokens - self._tokens
            wait = deficit / self.rate

        # Wait outside the lock
        if wait > 0:
            time.sleep(wait)

        # Replenish and consume after wait
        with self._lock:
            now = time.time()
            self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
            self._last = now
            self._tokens -= tokens


class RateLimiter:
    """Per-provider and global rate limiter.

    Example::

        limiter = RateLimiter()
        limiter.configure("ollama", rate=2.0, burst=10)
        # ...
        provider.chat(messages, tools=schemas)   # call limiter.before_call() first
    """

    def __init__(self, default_rate: float = 1.0, default_burst: int = 5):
        self._default_rate = default_rate
        self._default_burst = default_burst
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def configure(self, provider: str, rate: float, burst: int) -> None:
        with self._lock:
            self._buckets[provider] = TokenBucket(rate=rate, capacity=burst)

    def get_bucket(self, provider: str) -> TokenBucket:
        with self._lock:
            return self._buckets.get(provider) or TokenBucket(
                rate=self._default_rate, capacity=self._default_burst
            )

    def before_call(self, provider: str = "default") -> None:
        """Call this right before an LLM chat call."""
        self.get_bucket(provider).acquire()
