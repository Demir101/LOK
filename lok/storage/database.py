"""SQLite connection handling.

* One short-lived connection per unit of work (safe with Streamlit reruns).
* ``PRAGMA foreign_keys = ON`` on every connection.
* Explicit transactions: :meth:`Database.transaction` commits on success and
  rolls back on any exception.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from lok.storage.migrations import apply_migrations, current_schema_version


class DatabaseError(RuntimeError):
    """Raised for storage failures that callers should report to the user."""


class Database:
    """Thin wrapper around an SQLite database file."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield an autocommit connection for read-only work."""
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection inside ``BEGIN IMMEDIATE`` … ``COMMIT``/``ROLLBACK``."""
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")
        finally:
            connection.close()

    def initialize(self) -> int:
        """Create or migrate the schema. Returns the resulting schema version."""
        try:
            with self.transaction() as connection:
                apply_migrations(connection)
            with self.connect() as connection:
                return current_schema_version(connection)
        except sqlite3.DatabaseError as exc:
            raise DatabaseError(f"Could not initialise database at {self.path}: {exc}") from exc

    def schema_version(self) -> int:
        with self.connect() as connection:
            return current_schema_version(connection)
