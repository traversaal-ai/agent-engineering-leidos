"""Ambient trace context.

`contextvars` rather than explicit arguments, for one reason: without it, every
function that might ever emit a step needs `session_id` and `parent_step_id` in
its signature, and the interfaces in `contracts/` would be polluted with
observability plumbing. Students would then read `Retriever.retrieve` and see
tracing concerns mixed into a retrieval contract.

`contextvars` also does the right thing under `asyncio`: each task gets its own
copy, so Compare mode's four concurrent strategies cannot interleave their traces
even though they share a process.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace

from ai_backend.contracts.models import Strategy


@dataclass(frozen=True)
class TraceContext:
    session_id: str
    trace_id: str
    strategy: Strategy | None = None
    parent_step_id: str | None = None
    # Milliseconds to hold before each watched stage, so a room can follow a run.
    #
    # It rides on the trace context rather than on a module global or the session
    # record for two reasons. It is a property of *this run* — Compare mode runs
    # both strategies concurrently in one process, and a global would have them
    # pacing each other. And it is a presentation preference, which has no business
    # in the persisted session model beside the spend and the caps.
    #
    # Zero means no pause at all, which is the default and the only value any
    # non-interactive caller ever sets. See `_pause_for` in `trace.py` for why the
    # pause sits between stages and never inside a measurement.
    pace_ms: int = 0


_current: ContextVar[TraceContext | None] = ContextVar("axis_trace_context", default=None)


def current() -> TraceContext | None:
    return _current.get()


def require() -> TraceContext:
    """The active context, or a clear explanation of what the caller forgot."""
    ctx = _current.get()
    if ctx is None:
        raise RuntimeError(
            "No active trace context. Wrap the call in `with trace_context(...)` "
            "so emitted AgentSteps can be attributed to a session."
        )
    return ctx


@contextlib.contextmanager
def trace_context(
    *,
    session_id: str,
    trace_id: str,
    strategy: Strategy | None = None,
    pace_ms: int = 0,
) -> Iterator[TraceContext]:
    """Open a trace. Entered once per query, at the top of a pipeline."""
    ctx = TraceContext(
        session_id=session_id,
        trace_id=trace_id,
        strategy=strategy,
        pace_ms=pace_ms,
    )
    token: Token[TraceContext | None] = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


@contextlib.contextmanager
def child_of(step_id: str) -> Iterator[TraceContext]:
    """Nest subsequent steps under `step_id`.

    What makes the trace a tree. A ReAct iteration opens one of these, and every
    retrieval and tool call inside it is recorded as a child — which is how the
    Compare dashboard can show *why* an agentic run cost more rather than only
    that it did.
    """
    parent = require()
    ctx = replace(parent, parent_step_id=step_id)
    token: Token[TraceContext | None] = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)
