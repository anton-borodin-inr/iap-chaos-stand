"""Small SQLite helper. Each module owns its own database file and instance.

Writers use BEGIN IMMEDIATE, which serializes all writers of one database.
An idempotency lookup and the write that follows it therefore run atomically.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager


class Database:
    def __init__(self, path: str, schema: str) -> None:
        self.path = path
        self.schema = schema

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def init(self) -> None:
        conn = self.connect()
        try:
            conn.executescript(self.schema)
        finally:
            conn.close()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """A read transaction: every query inside sees one snapshot."""
        conn = self.connect()
        try:
            conn.execute("BEGIN")
            try:
                yield conn
            finally:
                conn.execute("COMMIT")
        finally:
            conn.close()
