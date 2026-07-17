"""Storage with optimistic locking support."""
from __future__ import annotations

import sqlite3
from typing import Any

from pulse.storage.engine import Storage


class OptimisticLockError(Exception):
    """Raised when a concurrent modification is detected."""
    pass


def with_optimistic_lock(
    storage: Storage,
    table: str,
    id_column: str,
    id_value: str,
    version_column: str,
    expected_version: int,
) -> bool:
    """Attempt an update with optimistic locking.

    Returns True if the update succeeded, False if the version has changed.
    Raises OptimisticLockError if the row no longer exists.
    """
    conn = storage._conn
    try:
        cursor = conn.execute(
            f"SELECT {version_column} FROM {table} WHERE {id_column} = ?",
            (id_value,),
        )
        row = cursor.fetchone()
        if row is None:
            raise OptimisticLockError(f"Row {id_value} not found in {table}")

        current_version = row[0] if row[0] is not None else 0
        if current_version != expected_version:
            return False

        conn.execute(
            f"UPDATE {table} SET {version_column} = ? WHERE {id_column} = ? AND {version_column} = ?",
            (expected_version + 1, id_value, expected_version),
        )
        conn.commit()
        return True
    except sqlite3.Error as e:
        raise OptimisticLockError(f"DB error during optimistic lock: {e}") from e
