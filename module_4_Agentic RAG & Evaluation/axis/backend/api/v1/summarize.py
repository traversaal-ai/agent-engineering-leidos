"""POST /api/v1/sessions/{id}/summarize — a structured overview of the documents.

The ordering is `query.py`'s, and for the same reasons:

    1. authenticate      (the token owns this session)
    2. CHECK THE CAP     ← before anything can cost money
    3. dispatch          (into the AI Backend)
    4. record the spend  (the actual cost, not the estimate)

Step 2 matters more here than anywhere else in the API. Summarization reads the whole
corpus, so its cost scales with how much a student uploaded rather than with what they
asked — it is the most expensive single action available after Compare, and the one a
student is most likely to press repeatedly while exploring. PRD Section 6 requires it
be refused before any LLM call when the cap is reached.

**Not a strategy, so not a query.** Its own endpoint rather than a `Strategy` value
passed to `/query`, because it does not retrieve at all — adding it to that enum would
make Compare mode's one variable stop meaning orchestration. See
`ai_backend/summarize.py`.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Request

from ai_backend.config.settings import Settings
from backend import dispatch
from backend.core.auth import require_matching_session
from backend.core.errors import ValidationError
from backend.core.limits import check_and_reserve
from backend.schemas.query import CitationOut
from backend.schemas.summarize import SummarizeRequest, SummaryResponse
from backend.store.repositories import SessionRecord

router = APIRouter(tags=["summarize"])


@router.post("/sessions/{session_id}/summarize", response_model=SummaryResponse)
async def summarize_documents(
    session_id: str,
    request: Request,
    body: SummarizeRequest | None = None,
    session: SessionRecord = Depends(require_matching_session),
) -> SummaryResponse:
    settings: Settings = request.app.state.settings
    sessions = request.app.state.sessions

    # (2) Cap check, before a provider is touched.
    budget = check_and_reserve(
        sessions=sessions,
        session_id=session.id,
        settings=settings,
        estimated_cost_usd=None,
    )

    ai = request.app.state.ai
    if ai is None:
        raise ValidationError(
            "Axis cannot summarise documents until its configuration is valid.",
            detail="Check /api/v1/health for what is wrong.",
        )

    # Names come from here rather than from the AI Backend, which indexes by id and
    # has no business holding a second copy that could drift (System Design §7). A
    # summary that referred to documents by uuid would be useless to read.
    corpus = body.corpus if body else dispatch.DEFAULT_CORPUS
    filenames = {
        d.id: d.filename
        for d in request.app.state.documents.list_for_session(session.id, corpus=corpus)
    }

    # (3) Dispatch. `document_ids` narrows what is read; absent, everything is.
    #
    # Not filtered here against `filenames`, though it easily could be. The filter that
    # matters is over what is *indexed*, and only the AI Backend's store knows that — a
    # document row exists from the moment of upload, including for one whose parse
    # failed, so validating against the Backend's own table would accept ids with no
    # chunks behind them and then quietly summarise nothing.
    summary = await dispatch.summarize(
        ai,
        session_id=session.id,
        budget=budget,
        corpus=corpus,
        filenames=filenames,
        document_ids=body.document_ids if body else None,
    )

    # (4) Correct the ledger to what was actually spent. Zero when nothing was
    # indexed — `summarize_session` makes no LLM call in that case, and charging for
    # a refusal would be wrong.
    cost = Decimal(summary.usage.cost_usd)
    if cost:
        sessions.record_spend(session.id, cost_usd=cost)

    return SummaryResponse(
        summary=summary.text,
        documents=summary.documents,
        citations=[
            CitationOut(
                document_id=c.document_id,
                filename=c.filename,
                source_location=c.source_location,
                quote=c.quote,
                kind=c.kind.value,
            )
            for c in summary.citations
        ],
        cost_usd=float(cost),
        prompt_tokens=summary.usage.prompt_tokens,
        completion_tokens=summary.usage.completion_tokens,
    )
