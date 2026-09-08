"""Session lifecycle — POST /api/v1/sessions and GET /api/v1/sessions/{id}.

`POST` is the only unauthenticated route besides health, for the obvious reason
that it is where a token comes from.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Request, status

from ai_backend.config.settings import Settings
from backend import dispatch
from backend.core.auth import require_matching_session
from backend.schemas.session import (
    SessionCreateRequest,
    SessionCreateResponse,
    SessionInfo,
)
from backend.store.repositories import SessionRecord

router = APIRouter(tags=["sessions"])


@router.post(
    "/sessions",
    response_model=SessionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    request: Request, body: SessionCreateRequest | None = None
) -> SessionCreateResponse:
    """Create an isolated workspace and issue its bearer token.

    Caps requested in the body are clamped to the server's configured maximum.
    Clamped rather than rejected so an instructor can freely ask for a *smaller*
    budget for a demo session; the clamp is what stops a caller raising its own
    ceiling, which would make the cap advisory.
    """
    settings: Settings = request.app.state.settings
    body = body or SessionCreateRequest()

    server_cost_cap = Decimal(str(settings.caps.max_cost_usd_per_session))
    server_request_cap = settings.caps.max_requests_per_session

    cost_cap = (
        min(Decimal(str(body.cap_cost_usd)), server_cost_cap)
        if body.cap_cost_usd is not None
        else server_cost_cap
    )
    request_cap = (
        min(body.cap_requests, server_request_cap)
        if body.cap_requests is not None
        else server_request_cap
    )

    record, token = request.app.state.sessions.create(
        cap_cost_usd=cost_cap,
        cap_requests=request_cap,
        ttl_seconds=settings.server.session_token_ttl_seconds,
    )

    return SessionCreateResponse(
        session_id=record.id,
        token=token,
        expires_at=record.expires_at,
        cap_cost_usd=float(record.cap_cost_usd),
        cap_requests=record.cap_requests,
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    request: Request,
    session: SessionRecord = Depends(require_matching_session),
) -> None:
    """Discard a session's indexed vectors.

    **What makes a classroom demo repeatable.** Indexing is the first thing a student
    watches, and until now it could only be watched once per session: the document
    limit refuses a second upload of the same file, and there was no way to clear one.
    An instructor running the demo for a second group had to clear cookies in front of
    the room.

    Only the vector index is deleted here. Documents, spend and trace history are all
    scoped to the session id, so the Frontend mints a fresh one and they become
    unreachable in a single move — no cascade of deletes to get half-right, and no
    window where a session exists with its index already gone. What this call adds is
    freeing the vectors, which nothing else would ever reclaim.

    Idempotent: deleting an already-empty index is not an error, and a student who
    double-clicks Start over should not see one.
    """
    ai = request.app.state.ai
    if ai is not None:
        # Every corpus, because "start over" means the session and a session now holds
        # more than one index scope. Deleting only the active one would leave the other
        # searchable under a session id the Frontend has already replaced — vectors
        # nothing can reach and nothing will ever reclaim.
        for corpus in dispatch.CORPORA:
            await ai.store.delete_session(session_id=dispatch.index_scope(session.id, corpus))
        # The cache is keyed on questions asked *against that index*. Leaving it
        # behind would let a "start over" demo answer the first question of the new
        # run from the old one — with citations pointing at documents that are gone.
        ai.forget_session(session.id)


@router.delete(
    "/sessions/{session_id}/corpus/{corpus}", status_code=status.HTTP_204_NO_CONTENT
)
async def clear_corpus(
    session_id: str,
    corpus: str,
    request: Request,
    session: SessionRecord = Depends(require_matching_session),
) -> None:
    """Empty one corpus so it can be filled again, leaving the other alone.

    **The missing half of the upload limit.** `DELETE /sessions/{id}` frees vectors but
    not `document` rows, so it could never be reused to clear a corpus: the rows would
    survive, keep counting against the limit, and list files whose chunks were gone.
    Without this route the only way past a full corpus was Start over, which throws away
    the other corpus, the spend history and every recorded run along with it.

    Both halves, in the order that fails safe: vectors first, then rows. Interrupted
    between them leaves orphaned rows listing zero chunks, which is visible and
    recoverable; the other order would leave rows counting against a limit for chunks
    that no longer exist.

    Idempotent, and an unknown corpus name clears nothing rather than erroring —
    `index_scope` maps it to the default, and there is nothing there to find.
    """
    name = corpus if corpus in dispatch.CORPORA else dispatch.DEFAULT_CORPUS
    ai = request.app.state.ai
    if ai is not None:
        await ai.store.delete_session(session_id=dispatch.index_scope(session.id, name))
        ai.invalidate_cache(dispatch.index_scope(session.id, name))
    request.app.state.documents.delete_corpus(session.id, name)


@router.delete("/sessions/{session_id}/turns", status_code=204)
async def start_new_conversation(
    session_id: str,
    request: Request,
    session: SessionRecord = Depends(require_matching_session),
) -> None:
    """Forget the conversation without forgetting the runs.

    Two different things to discard, and conflating them would trade one story for
    another: `DELETE /sessions/{id}` throws away the index so indexing can be watched
    again, while the Trace page's "read any run" story needs every run to survive.
    A student pressing "New conversation" wants neither — only that the next question
    stops being read as a follow-up to the last one.

    So this moves a watermark rather than deleting anything. Idempotent, and harmless
    on a session that has asked nothing.
    """
    request.app.state.conversation.start_new_conversation(session.id)


@router.get("/sessions/{session_id}", response_model=SessionInfo)
async def get_session(
    session_id: str,
    request: Request,
    session: SessionRecord = Depends(require_matching_session),
) -> SessionInfo:
    """Current state of a session, including remaining budget.

    The Frontend polls this so a student can watch their budget shrink rather
    than discovering the cap by hitting it. Seeing the number move is part of
    what the platform is trying to teach about agentic cost.
    """
    corpora = request.app.state.documents.counts_by_corpus(session.id)
    turns = request.app.state.conversation.recent_turns(
        session.id, limit=dispatch.MAX_HISTORY_TURNS
    )
    return SessionInfo(
        session_id=session.id,
        created_at=session.created_at,
        expires_at=session.expires_at,
        # Still the whole session, not the active corpus: this is what the session
        # holds, and the rail reports the per-corpus split beside it from `corpora`.
        document_count=sum(corpora.values()),
        corpora=corpora,
        turn_count=len(turns),
        request_count=session.request_count,
        cap_requests=session.cap_requests,
        spent_usd=float(session.spent_usd),
        cap_cost_usd=float(session.cap_cost_usd),
        remaining_usd=float(session.remaining_usd),
    )
