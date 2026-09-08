"""Persistence for the Backend layer — SQLite, no ORM.

See `db.py` for why migrations are plain `.sql` files, and `repositories.py` for
why session spend is read and incremented inside a transaction.
"""

from backend.store.db import Database
from backend.store.repositories import (
    ComparisonRunRepository,
    DocumentRecord,
    DocumentRepository,
    QueryRunRecord,
    QueryRunRepository,
    SessionRecord,
    SessionRepository,
    hash_token,
)

__all__ = [
    "ComparisonRunRepository",
    "Database",
    "DocumentRecord",
    "DocumentRepository",
    "QueryRunRecord",
    "QueryRunRepository",
    "SessionRecord",
    "SessionRepository",
    "hash_token",
]
