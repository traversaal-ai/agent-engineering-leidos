"""SQLite connection handling and migration application.

No ORM and no migration framework, for the same reason the observability library
is hand-written: the schema is small enough to read, and a student can see the
actual SQL. The trade-off is that schema changes are manual — add a numbered file
rather than editing an applied one.

`:memory:` is supported and is what the test suite uses, so acceptance tests
share no state and leave nothing behind.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class Database:
    """A SQLite database with its migrations applied.

    Holds one long-lived connection rather than opening per operation. For
    `:memory:` this is not optional — the database ceases to exist when the last
    connection to it closes.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            self._path,
            isolation_level=None,
            # FastAPI runs sync handlers in a threadpool, so the connection is
            # legitimately touched from more than one thread. Writes are
            # serialised by SQLite itself.
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        # Serialises multi-statement transactions on this one connection.
        #
        # Needed because there is a single shared connection and FastAPI runs
        # sync handlers in a threadpool. SQLite serialises individual statements
        # for us, but an explicit BEGIN…COMMIT from two threads at once would
        # nest — "cannot start a transaction within a transaction" — and the
        # read-then-increment in the cost cap would lose its atomicity.
        #
        # A lock is the right tool at this scale rather than a connection pool:
        # PRD Section 3 scopes Axis to one process on one machine for a class of
        # well under a few dozen sessions, and SQLite would serialise the writes
        # regardless. Reentrant so a transaction may call a helper that opens one.
        self._write_lock = threading.RLock()

        self.migrate()

    def migrate(self) -> None:
        """Apply every migration, in filename order.

        The files are written with `IF NOT EXISTS` throughout, so re-running is
        harmless — which keeps startup idempotent without a version table to get
        out of step with reality.
        """
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            self._conn.executescript(path.read_text(encoding="utf-8"))

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        cur = self._conn.cursor()
        try:
            yield cur
        finally:
            cur.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Cursor]:
        """Run statements atomically.

        Used for the read-then-write in the cost cap: reading a session's spend
        and then incrementing it must not interleave with another request doing
        the same, or two concurrent queries could each see room under the cap and
        both proceed — precisely the runaway the cap exists to prevent. A Compare
        run fires both strategies at once, so this is ordinary traffic rather
        than a contrived race.
        """
        with self._write_lock:
            cur = self._conn.cursor()
            try:
                cur.execute("BEGIN IMMEDIATE")
                yield cur
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise
            finally:
                cur.close()

    def close(self) -> None:
        self._conn.close()

    @property
    def path(self) -> str:
        return self._path
