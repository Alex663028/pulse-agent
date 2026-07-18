"""Tests for storage/lock.py - optimistic locking."""
from __future__ import annotations

from pulse.storage.lock import with_optimistic_lock


class TestOptimisticLock:
    def test_function_exists(self):
        """Verify the function is callable."""
        assert callable(with_optimistic_lock)
