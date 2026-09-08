"""Data access for the Backend layer.

Repositories rather than raw SQL at the route level, mainly so that reading a
session's spend and incrementing it can happen in one atomic place. Costs move
through `Decimal` and are stored as TEXT — see the note in
`ai_backend/observability/store.py` for why a float would erode a $2.00 cap.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel

from ai_backend.contracts.models import Strategy, new_id
from ai_backend.contracts.pipeline import DEFAULT_CORPUS
from backend.store.db import Database


def hash_token(token: str) -> str:
    """SHA-256 of a bearer token.

    Only the hash is stored. These tokens are short-lived and low-privilege, but
    a session store gets copied into backups and shared checkouts, and there is
    no reason to keep the plaintext.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SessionRecord(BaseModel):
    id: str
    created_at: datetime
    expires_at: datetime
    spent_usd: Decimal
    request_count: int
    cap_cost_usd: Decimal
    cap_requests: int

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at

    @property
    def remaining_usd(self) -> Decimal:
        return max(Decimal("0"), self.cap_cost_usd - self.spent_usd)

    @property
    def remaining_requests(self) -> int:
        return max(0, self.cap_requests - self.request_count)


class DocumentRecord(BaseModel):
    id: str
    session_id: str
    filename: str
    format: str
    byte_size: int
    upload_time: datetime
    status: str
    error: str | None = None
    # Which of the session's two corpora this document belongs to.
    #
    # Stored in `document_corpus` rather than on `document` — see
    # `migrations/003_corpus.sql` for why a column was not available. Defaulted so a
    # row written before that migration, and every test that builds a record without
    # naming one, lands in the same corpus `QueryContext` defaults to.
    corpus: str = DEFAULT_CORPUS


class QueryRunRecord(BaseModel):
    id: str
    session_id: str
    trace_id: str
    strategy: Strategy
    question: str
    final_answer: str | None = None
    status: str = "running"
    error: str | None = None
    started_at: datetime
    latency_ms: int = 0
    cost_usd: Decimal = Decimal("0")


class SessionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def create(
        self, *, cap_cost_usd: Decimal, cap_requests: int, ttl_seconds: int
    ) -> tuple[SessionRecord, str]:
        """Create a session and return it with its one-time plaintext token.

        The token exists in plaintext only in this return value and the response
        body. Caps are copied onto the row so that changing a server default
        mid-workshop cannot move a live session's limit up or down.
        """
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        record = SessionRecord(
            id=new_id(),
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            spent_usd=Decimal("0"),
            request_count=0,
            cap_cost_usd=cap_cost_usd,
            cap_requests=cap_requests,
        )
        with self._db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO session (id, token_hash, created_at, expires_at,
                                     spent_usd, request_count, cap_cost_usd,
                                     cap_requests)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    record.id,
                    hash_token(token),
                    record.created_at.isoformat(),
                    record.expires_at.isoformat(),
                    str(record.spent_usd),
                    record.request_count,
                    str(record.cap_cost_usd),
                    record.cap_requests,
                ),
            )
        return record, token

    def get(self, session_id: str) -> SessionRecord | None:
        with self._db.cursor() as cur:
            row = cur.execute("SELECT * FROM session WHERE id = ?", (session_id,)).fetchone()
        return _to_session(row) if row else None

    def get_by_token(self, token: str) -> SessionRecord | None:
        with self._db.cursor() as cur:
            row = cur.execute(
                "SELECT * FROM session WHERE token_hash = ?", (hash_token(token),)
            ).fetchone()
        return _to_session(row) if row else None

    def reserve_request(self, session_id: str) -> SessionRecord:
        """Atomically count one request against the session and return it.

        Read-and-increment in a single `BEGIN IMMEDIATE` transaction, because two
        concurrent queries could otherwise each read the same spend, each see
        room under the cap, and both proceed — which is exactly the runaway the
        cap exists to prevent.

        The returned record reflects state *after* the increment, so the caller's
        cap check is made against the request it is about to run.
        """
        with self._db.transaction() as cur:
            row = cur.execute("SELECT * FROM session WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                raise KeyError(session_id)
            cur.execute(
                "UPDATE session SET request_count = request_count + 1 WHERE id = ?",
                (session_id,),
            )
            record = _to_session(row)
        return record.model_copy(update={"request_count": record.request_count + 1})

    def record_spend(self, session_id: str, *, cost_usd: Decimal) -> None:
        """Add actual spend after a query completes.

        Kept separate from `reserve_request` because the pre-call estimate and
        the post-call actual are different numbers. The cap is checked against
        the estimate (it has to be — the call has not happened yet), and the
        ledger is corrected to the truth afterwards.
        """
        with self._db.transaction() as cur:
            row = cur.execute(
                "SELECT spent_usd FROM session WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise KeyError(session_id)
            total = Decimal(row["spent_usd"]) + cost_usd
            cur.execute(
                "UPDATE session SET spent_usd = ? WHERE id = ?", (str(total), session_id)
            )

    def delete_expired(self) -> int:
        """Remove sessions past their TTL. Cascades to their documents and runs."""
        with self._db.cursor() as cur:
            cur.execute(
                "DELETE FROM session WHERE expires_at < ?",
                (datetime.now(UTC).isoformat(),),
            )
            return cur.rowcount


class DocumentRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def count_for_session(self, session_id: str) -> int:
        with self._db.cursor() as cur:
            row = cur.execute(
                "SELECT COUNT(*) AS n FROM document WHERE session_id = ?", (session_id,)
            ).fetchone()
        return int(row["n"])

    def count_for_corpus(self, session_id: str, corpus: str) -> int:
        """How many documents this session holds *in one corpus*.

        **The upload limit counts this, not `count_for_session`**, and that is what
        makes holding both corpora possible at all. The demo set is exactly five files
        and the limit is five, so a session-wide count made `existing + 5 > 5` true for
        any existing document: one upload permanently blocked the demo corpus, and with
        no delete route the only escape was Start over.
        """
        with self._db.cursor() as cur:
            row = cur.execute(
                """
                SELECT COUNT(*) AS n
                  FROM document d
                  LEFT JOIN document_corpus c ON c.document_id = d.id
                 WHERE d.session_id = ?
                   AND COALESCE(c.corpus, ?) = ?
                """,
                (session_id, DEFAULT_CORPUS, corpus),
            ).fetchone()
        return int(row["n"])

    def counts_by_corpus(self, session_id: str) -> dict[str, int]:
        """Every corpus this session holds, and how many documents are in each.

        One query rather than one per corpus, because `_chrome()` renders the rail on
        every page and banks on making no round trip it does not already make.
        """
        with self._db.cursor() as cur:
            rows = cur.execute(
                """
                SELECT COALESCE(c.corpus, ?) AS corpus, COUNT(*) AS n
                  FROM document d
                  LEFT JOIN document_corpus c ON c.document_id = d.id
                 WHERE d.session_id = ?
                 GROUP BY COALESCE(c.corpus, ?)
                """,
                (DEFAULT_CORPUS, session_id, DEFAULT_CORPUS),
            ).fetchall()
        return {str(r["corpus"]): int(r["n"]) for r in rows}

    def add(
        self,
        *,
        session_id: str,
        filename: str,
        fmt: str,
        byte_size: int,
        status: str = "pending",
        error: str | None = None,
        corpus: str = DEFAULT_CORPUS,
    ) -> DocumentRecord:
        record = DocumentRecord(
            id=new_id(),
            session_id=session_id,
            filename=filename,
            format=fmt,
            byte_size=byte_size,
            upload_time=datetime.now(UTC),
            status=status,
            error=error,
            corpus=corpus,
        )
        with self._db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO document (id, session_id, filename, format, byte_size,
                                      upload_time, status, error)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    record.id,
                    record.session_id,
                    record.filename,
                    record.format,
                    record.byte_size,
                    record.upload_time.isoformat(),
                    record.status,
                    record.error,
                ),
            )
            # Both rows in one cursor, so a document can never exist without a corpus.
            cur.execute(
                "INSERT INTO document_corpus (document_id, corpus) VALUES (?,?)",
                (record.id, record.corpus),
            )
        return record

    def list_for_session(
        self, session_id: str, *, corpus: str | None = None
    ) -> list[DocumentRecord]:
        """This session's documents, all of them or just one corpus's.

        `corpus=None` means every corpus, which is what the raw listing wants; the
        Frontend passes the active one, because a document list that shows files the
        active index cannot reach is a list of things that will not be found.
        """
        clause = "AND COALESCE(c.corpus, ?) = ?" if corpus is not None else ""
        params: tuple[object, ...] = (
            (DEFAULT_CORPUS, session_id, DEFAULT_CORPUS, corpus)
            if corpus is not None
            else (DEFAULT_CORPUS, session_id)
        )
        with self._db.cursor() as cur:
            rows = cur.execute(
                f"""
                SELECT d.*, COALESCE(c.corpus, ?) AS corpus
                  FROM document d
                  LEFT JOIN document_corpus c ON c.document_id = d.id
                 WHERE d.session_id = ?
                   {clause}
                 ORDER BY d.upload_time
                """,
                params,
            ).fetchall()
        return [
            DocumentRecord(
                id=r["id"],
                session_id=r["session_id"],
                filename=r["filename"],
                format=r["format"],
                byte_size=r["byte_size"],
                upload_time=r["upload_time"],
                status=r["status"],
                error=r["error"],
                corpus=r["corpus"],
            )
            for r in rows
        ]

    def delete_corpus(self, session_id: str, corpus: str) -> int:
        """Drop one corpus's document rows. Returns how many were removed.

        The vector scope is the caller's job — this owns the `document` table and
        nothing else. Both halves are needed for a corpus to be *reloadable*, which is
        the gap that made Start over the only way to recover from a full session.
        """
        with self._db.cursor() as cur:
            cur.execute(
                """
                DELETE FROM document
                 WHERE session_id = ?
                   AND id IN (
                       SELECT d.id
                         FROM document d
                         LEFT JOIN document_corpus c ON c.document_id = d.id
                        WHERE d.session_id = ?
                          AND COALESCE(c.corpus, ?) = ?
                   )
                """,
                (session_id, session_id, DEFAULT_CORPUS, corpus),
            )
            return cur.rowcount

    def set_status(self, document_id: str, *, status: str, error: str | None = None) -> None:
        with self._db.cursor() as cur:
            cur.execute(
                "UPDATE document SET status = ?, error = ? WHERE id = ?",
                (status, error, document_id),
            )


class QueryRunRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def start(
        self, *, session_id: str, trace_id: str, strategy: Strategy, question: str
    ) -> QueryRunRecord:
        record = QueryRunRecord(
            id=new_id(),
            session_id=session_id,
            trace_id=trace_id,
            strategy=strategy,
            question=question,
            started_at=datetime.now(UTC),
        )
        with self._db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO query_run (id, session_id, trace_id, strategy, question,
                                       status, started_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    record.id,
                    record.session_id,
                    record.trace_id,
                    str(record.strategy),
                    record.question,
                    record.status,
                    record.started_at.isoformat(),
                ),
            )
        return record

    def finish(
        self,
        run_id: str,
        *,
        final_answer: str | None,
        status: str,
        latency_ms: int,
        cost_usd: Decimal,
        error: str | None = None,
    ) -> None:
        with self._db.cursor() as cur:
            cur.execute(
                """
                UPDATE query_run
                   SET final_answer = ?, status = ?, latency_ms = ?, cost_usd = ?,
                       error = ?
                 WHERE id = ?
                """,
                (final_answer, status, latency_ms, str(cost_usd), error, run_id),
            )


class ConversationRepository:
    """What this session has already asked, and where the current thread starts.

    **Reads `query_run` rather than a table of its own.** Every question and its
    answer is already recorded there; a `turn` table would be a second source of
    truth for the same fact and the two would eventually disagree. See
    `migrations/002_conversation.sql`.

    Why the Backend owns this at all, rather than the AI Backend keeping the history
    in memory: Section 6.1 puts persistence here, and — more practically — the ask
    form must work with JavaScript disabled, so the browser cannot be the one holding
    the transcript. A client-supplied history would also be a way to put arbitrary
    text into a prompt.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def recent_turns(self, session_id: str, *, limit: int) -> list[tuple[str, str]]:
        """The last `limit` completed exchanges, oldest first.

        Only runs that produced an answer: a failed or refused run has nothing a
        follow-up could refer back to, and offering "I could not find that" as
        context would invite the rewriter to resolve a pronoun against a non-answer.

        Ordered newest-first in SQL so `LIMIT` keeps the *recent* ones, then reversed
        so the prompt reads forwards. Getting that backwards would hand the rewriter
        the oldest three turns of a long conversation, which is worse than none.
        """
        since = self.conversation_since(session_id)
        clause = "AND started_at >= ?" if since else ""
        params: tuple[object, ...] = (session_id, since) if since else (session_id,)

        with self._db.cursor() as cur:
            cur.execute(
                f"""
                SELECT question, final_answer
                  FROM query_run
                 WHERE session_id = ?
                   AND status = 'ok'
                   AND final_answer IS NOT NULL
                   AND final_answer <> ''
                   {clause}
                 ORDER BY started_at DESC, rowid DESC
                 LIMIT ?
                """,
                (*params, limit),
            )
            rows = cur.fetchall()

        return [(str(r["question"]), str(r["final_answer"])) for r in reversed(rows)]

    def conversation_since(self, session_id: str) -> str | None:
        with self._db.cursor() as cur:
            cur.execute(
                "SELECT since FROM conversation WHERE session_id = ?", (session_id,)
            )
            row = cur.fetchone()
        return str(row["since"]) if row else None

    def start_new_conversation(self, session_id: str) -> None:
        """Forget the thread without forgetting the runs.

        Two different things to throw away, and conflating them is how the Trace
        page would lose its history to fix a memory demo. `POST /reset` still
        discards everything; this discards only what a follow-up can refer to.
        """
        with self._db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversation (session_id, since) VALUES (?,?)
                ON CONFLICT(session_id) DO UPDATE SET since = excluded.since
                """,
                (session_id, datetime.now(UTC).isoformat()),
            )


class ComparisonRunRepository:
    """One question across both strategies.

    A partially-failing run needs somewhere to record *which* strategy failed —
    Section 11 requires that strategy's column show its failure rather than a
    blank cell.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, *, session_id: str, question: str) -> str:
        run_id = new_id()
        with self._db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO comparison_run (id, session_id, question, created_at, metrics)
                VALUES (?,?,?,?,?)
                """,
                (run_id, session_id, question, datetime.now(UTC).isoformat(), "{}"),
            )
        return run_id

    def set_metrics(self, run_id: str, metrics: dict[str, object]) -> None:
        with self._db.cursor() as cur:
            cur.execute(
                "UPDATE comparison_run SET metrics = ? WHERE id = ?",
                (json.dumps(metrics, default=str), run_id),
            )

    def get_metrics(self, run_id: str) -> dict[str, object]:
        with self._db.cursor() as cur:
            row = cur.execute(
                "SELECT metrics FROM comparison_run WHERE id = ?", (run_id,)
            ).fetchone()
        return json.loads(row["metrics"]) if row else {}


def _to_session(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        id=row["id"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        spent_usd=Decimal(row["spent_usd"]),
        request_count=row["request_count"],
        cap_cost_usd=Decimal(row["cap_cost_usd"]),
        cap_requests=row["cap_requests"],
    )
