"""Where `AgentStep`s go, and how the live trace gets pushed to the browser.

Redaction happens here, at the boundary, for every implementation — so no store
can accidentally persist an unscrubbed step.

The `subscribe()` mechanism is what makes PRD Section 6's "streams to the trace
view within 2 seconds of that step completing" achievable. A polling SSE endpoint
would meet the letter of that criterion but feel laggy in a live demo, and the
whole point is that a class watches steps appear as they happen. Publishing on
write costs almost nothing and is built in now rather than retrofitted at
Milestone 0.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol, runtime_checkable

from ai_backend.contracts.models import AgentStep, StepStatus, StepType, Strategy, Usage
from ai_backend.observability.redact import redact_step, redact_text


@runtime_checkable
class AgentStepStore(Protocol):
    async def append(self, step: AgentStep) -> None: ...

    async def list_steps(
        self, *, session_id: str, trace_id: str | None = None
    ) -> list[AgentStep]: ...

    async def get_step(self, step_id: str) -> AgentStep | None: ...

    async def set_narration(self, step_id: str, narration: str) -> None: ...

    def subscribe(self, session_id: str) -> asyncio.Queue[AgentStep]: ...

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[AgentStep]) -> None: ...


class _Publisher:
    """Fan-out to any SSE connections currently watching a session."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[AgentStep]]] = {}

    def subscribe(self, session_id: str) -> asyncio.Queue[AgentStep]:
        queue: asyncio.Queue[AgentStep] = asyncio.Queue()
        self._subscribers.setdefault(session_id, []).append(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[AgentStep]) -> None:
        queues = self._subscribers.get(session_id)
        if not queues:
            return
        if queue in queues:
            queues.remove(queue)
        if not queues:
            del self._subscribers[session_id]

    def publish(self, step: AgentStep) -> None:
        # A slow or vanished browser must never stall the pipeline producing the
        # step, so this is fire-and-forget onto unbounded queues.
        for queue in self._subscribers.get(step.session_id, []):
            queue.put_nowait(step)


class InMemoryStepStore:
    """The store used by tests and by anything that must not touch disk.

    Also what makes the whole test suite runnable with no filesystem state, which
    keeps acceptance tests independent of each other.
    """

    def __init__(self, *, secrets: tuple[str, ...] = ()) -> None:
        self._steps: list[AgentStep] = []
        self._secrets = secrets
        self._publisher = _Publisher()

    async def append(self, step: AgentStep) -> None:
        """Record a step, replacing an earlier write of the same one.

        **Replace, not append**, because a step is now written twice: once as it
        starts and once as it finishes, under the same id. Appending would leave
        the running row behind, so every finished trace would carry a phantom
        duplicate of each step — doubling what the raw trace shows, what the
        evaluation harness counts, and what a `retrievals` figure in the
        comparison table means.

        `SqliteStepStore` gets this for free: `id` is its primary key and it
        inserts with `OR REPLACE`. This is the store the whole suite runs against,
        and the two have disagreed before — over whether `set_narration` redacts —
        so `test_the_store_replaces_a_step_rather_than_duplicating_it` asserts it
        of both.
        """
        safe = redact_step(step, self._secrets)
        for i, existing in enumerate(self._steps):
            if existing.id == safe.id:
                self._steps[i] = safe
                break
        else:
            self._steps.append(safe)
        self._publisher.publish(safe)

    async def list_steps(
        self, *, session_id: str, trace_id: str | None = None
    ) -> list[AgentStep]:
        matching = [
            s
            for s in self._steps
            if s.session_id == session_id and (trace_id is None or s.trace_id == trace_id)
        ]
        # Ordered by creation sequence, not by append order and not by
        # `started_at`. A step is *written* when it completes, so append order puts
        # a parent after its own children; and `started_at` is not fine-grained
        # enough to separate them on Windows, where a retrieval and its embedding
        # call can share an identical timestamp. See `next_seq` in contracts/models.
        return sorted(matching, key=lambda s: s.seq)

    async def get_step(self, step_id: str) -> AgentStep | None:
        return next((s for s in self._steps if s.id == step_id), None)

    async def set_narration(self, step_id: str, narration: str) -> None:
        # Redacted, exactly as `append` is. This was missed when narration was
        # first stubbed: the SQLite store scrubbed here and this one did not, and
        # the existing boundary test only exercised `append` — so the two
        # implementations disagreed about whether narration is a leak path, and the
        # one used by the whole test suite was the permissive one.
        #
        # Narration is LLM output *about* a step's raw fields, so a key echoed back
        # in a provider error can be quoted straight into it. It needs the same
        # treatment as any other free-text field.
        safe = redact_text(narration, self._secrets)
        for i, step in enumerate(self._steps):
            if step.id == step_id:
                self._steps[i] = step.model_copy(update={"narration": safe})
                return

    def subscribe(self, session_id: str) -> asyncio.Queue[AgentStep]:
        return self._publisher.subscribe(session_id)

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[AgentStep]) -> None:
        self._publisher.unsubscribe(session_id, queue)

    # Test affordance, not part of the Protocol.
    @property
    def all_steps(self) -> list[AgentStep]:
        return list(self._steps)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_step (
    id                 TEXT PRIMARY KEY,
    seq                INTEGER NOT NULL DEFAULT 0,
    session_id         TEXT NOT NULL,
    trace_id           TEXT NOT NULL,
    parent_step_id     TEXT,
    step_type          TEXT NOT NULL,
    status             TEXT NOT NULL,
    strategy           TEXT,
    label              TEXT NOT NULL DEFAULT '',
    raw_input          TEXT,
    raw_output         TEXT,
    narration          TEXT,
    started_at         TEXT NOT NULL,
    duration_ms        INTEGER NOT NULL DEFAULT 0,
    prompt_tokens      INTEGER NOT NULL DEFAULT 0,
    completion_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_usd           TEXT NOT NULL DEFAULT '0',
    error              TEXT,
    attributes         TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_agent_step_session ON agent_step(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_agent_step_trace   ON agent_step(trace_id, seq);
"""


class SqliteStepStore:
    """The runtime store.

    Steps survive a restart, which is what lets a student replay a trace after
    class and lets the evaluation harness score runs it did not observe live.

    `cost_usd` is stored as TEXT and reloaded through `Decimal`. SQLite has no
    decimal type, and rounding a per-call cost through a float and then summing
    hundreds of them is exactly how a $2 cap quietly becomes a $2.03 cap.
    """

    def __init__(self, db_path: Path | str, *, secrets: tuple[str, ...] = ()) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._secrets = secrets
        self._publisher = _Publisher()
        self._lock = asyncio.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        # WAL lets the SSE reader poll while a pipeline is still writing.
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    async def append(self, step: AgentStep) -> None:
        safe = redact_step(step, self._secrets)
        async with self._lock:
            await asyncio.to_thread(self._insert, safe)
        self._publisher.publish(safe)

    def _insert(self, step: AgentStep) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_step (
                    id, seq, session_id, trace_id, parent_step_id, step_type, status,
                    strategy, label, raw_input, raw_output, narration, started_at,
                    duration_ms, prompt_tokens, completion_tokens, cost_usd, error,
                    attributes
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    step.id,
                    step.seq,
                    step.session_id,
                    step.trace_id,
                    step.parent_step_id,
                    str(step.step_type),
                    str(step.status),
                    str(step.strategy) if step.strategy else None,
                    step.label,
                    step.raw_input,
                    step.raw_output,
                    step.narration,
                    step.started_at.isoformat(),
                    step.duration_ms,
                    step.usage.prompt_tokens,
                    step.usage.completion_tokens,
                    str(step.usage.cost_usd),
                    step.error,
                    json.dumps(step.attributes, default=str),
                ),
            )

    @staticmethod
    def _strategy_of(stored: str | None) -> Strategy | None:
        """A persisted strategy name, or `None` if this build no longer knows it.

        **Tolerant on purpose, and it is the read side only.** `agent_step.strategy` is
        a plain `TEXT` column with no CHECK constraint, so a database can outlive the
        enum that wrote it — a strategy that was removed, or a row written by a newer
        build. `Strategy(...)` raises `ValueError` on an unknown value, and because
        `list_steps` maps every row, one such row would take down the entire trace fetch
        for that session with a 500.

        Degrading to `None` is the same shape as a step that never had a strategy: the
        trace still renders, the step still shows its type, duration and cost, and only
        the strategy label is missing. A trace that mostly loads beats a trace that does
        not.

        The write side stays strict — nothing can *persist* an unknown strategy, because
        it is typed on the way in.
        """
        if not stored:
            return None
        try:
            return Strategy(stored)
        except ValueError:
            return None

    @classmethod
    def _row_to_step(cls, row: sqlite3.Row) -> AgentStep:
        return AgentStep(
            id=row["id"],
            seq=row["seq"],
            session_id=row["session_id"],
            trace_id=row["trace_id"],
            parent_step_id=row["parent_step_id"],
            step_type=StepType(row["step_type"]),
            status=StepStatus(row["status"]),
            strategy=cls._strategy_of(row["strategy"]),
            label=row["label"],
            raw_input=row["raw_input"],
            raw_output=row["raw_output"],
            narration=row["narration"],
            started_at=row["started_at"],
            duration_ms=row["duration_ms"],
            usage=Usage(
                prompt_tokens=row["prompt_tokens"],
                completion_tokens=row["completion_tokens"],
                cost_usd=row["cost_usd"],
            ),
            error=row["error"],
            attributes=json.loads(row["attributes"]),
        )

    async def list_steps(
        self, *, session_id: str, trace_id: str | None = None
    ) -> list[AgentStep]:
        def _query() -> list[AgentStep]:
            sql = "SELECT * FROM agent_step WHERE session_id = ?"
            params: list[object] = [session_id]
            if trace_id is not None:
                sql += " AND trace_id = ?"
                params.append(trace_id)
            sql += " ORDER BY seq, rowid"
            with self._connect() as conn:
                return [self._row_to_step(r) for r in conn.execute(sql, params)]

        return await asyncio.to_thread(_query)

    async def get_step(self, step_id: str) -> AgentStep | None:
        def _query() -> AgentStep | None:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM agent_step WHERE id = ?", (step_id,)
                ).fetchone()
            return self._row_to_step(row) if row else None

        return await asyncio.to_thread(_query)

    async def set_narration(self, step_id: str, narration: str) -> None:
        # Was a whole throwaway `AgentStep` built to scrub one string, which also
        # consumed a number from the global `seq` counter for a step that never
        # existed. Same guarantee, one call.
        safe = redact_text(narration, self._secrets)

        def _update() -> None:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE agent_step SET narration = ? WHERE id = ?", (safe, step_id)
                )

        async with self._lock:
            await asyncio.to_thread(_update)

    def subscribe(self, session_id: str) -> asyncio.Queue[AgentStep]:
        return self._publisher.subscribe(session_id)

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[AgentStep]) -> None:
        self._publisher.unsubscribe(session_id, queue)


def aggregate_usage(steps: Iterable[AgentStep]) -> Usage:
    """Total cost and tokens across steps.

    Used by the Compare dashboard and by the cost cap. Summing per-step `Usage`
    is the only place total spend is derived from — there is no separate counter
    that could drift out of agreement with the trace a student is looking at.
    """
    total = Usage()
    for step in steps:
        total = total + step.usage
    return total
