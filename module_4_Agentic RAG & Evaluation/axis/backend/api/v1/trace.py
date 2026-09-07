"""Trace endpoints — the live SSE stream and lazy narration.

    GET  /api/v1/sessions/{id}/trace                       (SSE)
    GET  /api/v1/sessions/{id}/trace/steps                 (snapshot)
    POST /api/v1/sessions/{id}/trace/{step_id}/narrate

SSE is hand-rolled rather than pulled from a library, matching the choice made
for the observability layer: the wire format is four lines of text, and a student
who can read `data: {...}\\n\\n` off the network tab understands the live trace
completely. A dependency would hide the one interesting thing here.

The stream pushes rather than polls, subscribing to the step store's publisher.
Polling could meet PRD Section 6's two-second bound on paper while still feeling
laggy in front of a class, and "watch the steps appear" is the entire point of the
feature.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ai_backend.observability.store import AgentStepStore
from ai_backend.observability.trace import get_store
from backend import dispatch
from backend.core.auth import require_matching_session
from backend.core.errors import NotFoundError, ValidationError
from backend.schemas.trace import NarrateResponse, TraceStep
from backend.store.repositories import SessionRecord

router = APIRouter(tags=["trace"])

# Sent when the stream is idle, to keep proxies and browsers from closing it.
# An SSE comment line, which clients ignore.
_KEEPALIVE = ": keepalive\n\n"
_KEEPALIVE_SECONDS = 15.0


@router.get("/sessions/{session_id}/trace/steps", response_model=list[TraceStep])
async def list_trace_steps(
    session_id: str,
    trace_id: str | None = None,
    session: SessionRecord = Depends(require_matching_session),
) -> list[TraceStep]:
    """Every step recorded so far.

    The snapshot a client fetches on page load, before subscribing to the live
    stream — and what makes a trace re-readable after the run has finished.
    """
    steps = await get_store().list_steps(session_id=session.id, trace_id=trace_id)
    return [TraceStep.from_agent_step(s) for s in steps]


@router.get("/sessions/{session_id}/trace/steps/{step_id}", response_model=TraceStep)
async def get_trace_step(
    session_id: str,
    step_id: str,
    session: SessionRecord = Depends(require_matching_session),
) -> TraceStep:
    """One step, for the stage detail pane.

    The pane is rendered from a single step, and fetching the session's entire trace
    to render one of them would send a workshop's accumulated history over the wire
    on every click — the panes are meant to be clicked through freely, which is the
    whole navigation model.

    The ownership check is the same one `narrate_step` makes, for the same reason: a
    step id is a bare uuid, and without it any student could read the raw input and
    output of another session's steps. Answering "no such step" rather than "not
    yours" avoids confirming that the id exists.
    """
    step = await get_store().get_step(step_id)
    if step is None or step.session_id != session.id:
        raise NotFoundError(f"No trace step {step_id!r} in this session.")
    return TraceStep.from_agent_step(step)


async def trace_event_stream(
    store: AgentStepStore,
    *,
    session_id: str,
    is_disconnected: Callable[[], Awaitable[bool]],
    keepalive_seconds: float = _KEEPALIVE_SECONDS,
    since_seq: int = 0,
) -> AsyncIterator[str]:
    """The SSE body: replay what has happened, then stream what happens next.

    A module-level generator taking `is_disconnected` as a parameter rather than a
    closure over `Request`, for a specific reason: `httpx.ASGITransport` buffers
    a response body to completion, so an open-ended stream can never be read
    through it. Testing this logic through HTTP is therefore impossible — not
    because of anything here, but because of how the test transport works.
    Injecting the disconnect check makes the interesting behaviour (replay
    ordering, live delivery, keepalives, prompt teardown) directly testable, and
    is better factored regardless.

    `since_seq` suppresses replay of steps at or below that sequence number. A
    session accumulates every question's steps, so an unfiltered replay meant the
    second question's canvas filled with the first question's pipeline before the
    new run had emitted anything. Passing the highest `seq` already seen makes the
    stream show one run — and makes a dropped connection resumable rather than
    duplicating everything on reconnect.
    """
    queue = store.subscribe(session_id)
    try:
        # Replay first, so a client connecting mid-run sees a complete trace
        # rather than joining partway through.
        for step in await store.list_steps(session_id=session_id):
            if step.seq > since_seq:
                yield _sse(TraceStep.from_agent_step(step))

        # The next step and the client going away are raced against each other,
        # rather than polling `is_disconnected()` between queue waits. Polling
        # would leave a closed connection holding this generator open for up to
        # one keepalive interval, which a student reloading the page turns into a
        # pile of orphaned generators.
        while True:
            next_step = asyncio.ensure_future(queue.get())
            gone = asyncio.ensure_future(is_disconnected())
            done, pending = await asyncio.wait(
                {next_step, gone},
                timeout=keepalive_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()

            if next_step in done:
                yield _sse(TraceStep.from_agent_step(next_step.result()))
                continue
            if gone in done and gone.result():
                return
            if not done:
                # Idle. Keeps proxies and browsers from closing the stream.
                yield _KEEPALIVE
    finally:
        # Always unsubscribe. Otherwise every page reload leaks a queue that
        # keeps accumulating steps for the rest of the session.
        store.unsubscribe(session_id, queue)


@router.get("/sessions/{session_id}/trace")
async def stream_trace(
    session_id: str,
    request: Request,
    since_seq: int = 0,
    session: SessionRecord = Depends(require_matching_session),
) -> StreamingResponse:
    """Stream `AgentStep`s as they are recorded.

    `since_seq` skips replaying steps the caller already has — pass the highest
    `seq` seen so far to watch one run rather than the whole session's history.
    """
    return StreamingResponse(
        trace_event_stream(
            get_store(),
            session_id=session.id,
            is_disconnected=request.is_disconnected,
            since_seq=since_seq,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Tells nginx not to buffer, which would defeat streaming entirely.
            "X-Accel-Buffering": "no",
        },
    )


def _sse(step: TraceStep) -> str:
    """Format one step as an SSE event.

    Named `agent_step` so the HTMX SSE extension can bind to it specifically
    rather than to every message on the channel.
    """
    payload = json.dumps(step.model_dump(mode="json"))
    return f"event: agent_step\ndata: {payload}\n\n"


@router.post(
    "/sessions/{session_id}/trace/{step_id}/narrate", response_model=NarrateResponse
)
async def narrate_step(
    session_id: str,
    step_id: str,
    request: Request,
    session: SessionRecord = Depends(require_matching_session),
) -> NarrateResponse:
    """Generate a plain-language explanation of one step, then cache it.

    Cache-first is the requirement, not an optimisation. PRD Section 6:

        Given a completed trace, when a student toggles to narrated view for the
        first time on a given step, then a plain-language narration is generated
        and cached; when toggled again for the same step, then the cached
        narration is shown without a new LLM call.

    So the cache check precedes generation, and `generated` reports which path was
    taken — which is how the acceptance test observes that a second toggle made no
    LLM call.

    The session ownership check is not incidental: a step id is a bare uuid, and
    without it any student could narrate — and so read the raw input and output of —
    another session's steps. Answering "no such step" rather than "not yours" avoids
    confirming that the id exists.
    """
    store = get_store()
    step = await store.get_step(step_id)
    if step is None or step.session_id != session.id:
        raise NotFoundError(f"No trace step {step_id!r} in this session.")

    if step.narration:
        return NarrateResponse(step_id=step_id, narration=step.narration, generated=False)

    ai = request.app.state.ai
    if ai is None:
        raise ValidationError(
            "Axis cannot narrate a step until its configuration is valid.",
            detail="Check /api/v1/health for what is wrong.",
        )

    narration = await dispatch.narrate_step(ai, store, step=step)
    return NarrateResponse(step_id=step_id, narration=narration, generated=True)
