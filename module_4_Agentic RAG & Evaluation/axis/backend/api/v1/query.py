"""POST /api/v1/sessions/{id}/query — ask one question of one strategy.

The ordering inside `submit_query` is the whole substance of this module, and it
is not negotiable:

    1. authenticate      (the token owns this session)
    2. validate          (the strategy exists)
    3. CHECK THE CAP     ← before anything can cost money
    4. dispatch          (into the AI Backend)
    5. record the spend  (the actual cost, not the estimate)

Step 3 sits above step 4 because PRD Section 6 requires a capped session be
refused "before any LLM call is made". Any arrangement where the cap is consulted
inside a pipeline satisfies the wording loosely and the intent not at all — by
then a provider has been paid.

Step 5 exists because the estimate and the actual are different numbers. The cap
must be checked against an estimate (the call has not happened yet), and the
ledger corrected to the truth afterwards.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, Request

from ai_backend.config.settings import Settings
from ai_backend.contracts.models import Citation, SourceKind
from ai_backend.errors import AxisError
from backend import dispatch
from backend.core.auth import require_matching_session
from backend.core.limits import check_and_reserve
from backend.schemas.query import CitationOut, QueryRequest, QueryResponse
from backend.store.repositories import SessionRecord

router = APIRouter(tags=["query"])
logger = logging.getLogger("axis.backend.query")


def _citation_out(citation: Citation, filenames: dict[str, str]) -> CitationOut:
    """One citation for the wire, with the two kinds kept apart.

    Shared by this route and `compare.py`, which previously each built their own and
    would otherwise both need the same web-citation special case — and only one of
    them would have got it.
    """
    if citation.kind is SourceKind.WEB:
        return CitationOut(
            # No document id and no filename lookup: there is no document. The title
            # the search provider returned stands in as the display name.
            filename=citation.filename or citation.url,
            source_location=citation.source_location,
            quote=citation.quote,
            kind=SourceKind.WEB.value,
            url=citation.url,
        )
    return CitationOut(
        document_id=citation.document_id,
        filename=citation.filename
        or filenames.get(citation.document_id, "unknown document"),
        source_location=citation.source_location,
        quote=citation.quote,
        kind=SourceKind.DOCUMENT.value,
    )


@router.post("/sessions/{session_id}/query", response_model=QueryResponse)
async def submit_query(
    session_id: str,
    body: QueryRequest,
    request: Request,
    session: SessionRecord = Depends(require_matching_session),
) -> QueryResponse:
    settings: Settings = request.app.state.settings
    sessions = request.app.state.sessions
    runs = request.app.state.query_runs
    conversation = request.app.state.conversation

    # (3) Cap check. Raises BudgetExceededError → HTTP 429 without having
    # touched a provider: nothing reachable from here holds one.
    budget = check_and_reserve(
        sessions=sessions,
        session_id=session.id,
        settings=settings,
        estimated_cost_usd=None,
    )

    run = runs.start(
        session_id=session.id,
        trace_id="pending",
        strategy=body.strategy,
        question=body.question,
    )

    # (4) Dispatch. The Backend learns nothing here about how the answer is made.
    try:
        answer = await dispatch.run_query(
            session_id=session.id,
            question=body.question,
            strategy=body.strategy,
            budget=budget,
            pace_ms=body.pace_ms,
            # Which corpus to search. Not validated here: `index_scope` narrows an
            # unknown name to the empty corpus, so a forged value finds nothing rather
            # than 422-ing a student mid-demo.
            corpus=body.corpus,
            # Permission only. The AI Backend combines it with whether a provider was
            # ever configured, so this cannot switch the web *on* where the deployment
            # said no — see `AgenticRagPipeline.run`.
            web_enabled=body.web_search,
            # What this session has already asked and been told. Read here rather
            # than inside the AI Backend because Section 6.1 puts persistence in
            # this layer — and because the browser cannot be the one holding it: the
            # ask form works with JavaScript disabled, and a client-supplied history
            # would be a way to put arbitrary text into a prompt.
            #
            # Handed to *both* strategies. Naive RAG ignores it, which is the point:
            # it is the baseline, and the contrast a student sees is a follow-up that
            # resolves against one strategy and not the other. Filtering it out here
            # would move that decision from the pipeline — where it is visible in the
            # absence of a `rewrite` step — into a Backend `if`.
            history=conversation.recent_turns(
                session.id, limit=dispatch.MAX_HISTORY_TURNS
            ),
            cache_enabled=body.cache,
        )
    except AxisError as exc:
        # A failed run is still a run: it is recorded, and the request it consumed
        # is not refunded. That is deliberate — a strategy that fails expensively
        # has still spent the class's money, and hiding that would misrepresent
        # the comparison.
        runs.finish(
            run.id,
            final_answer=None,
            status="error",
            latency_ms=0,
            cost_usd=Decimal("0"),
            error=f"{exc.code}: {exc.message}",
        )
        raise

    # (5) Correct the ledger to what was actually spent.
    cost = dispatch.total_cost(answer)
    sessions.record_spend(session.id, cost_usd=cost)
    runs.finish(
        run.id,
        final_answer=answer.text,
        status="ok",
        latency_ms=answer.latency_ms,
        cost_usd=cost,
    )

    # Citations arrive carrying `document_id` but no filename: the AI Backend
    # indexes by id and the `document` table owns names (System Design §7), so a
    # second copy down there could only drift. Resolving here keeps one source of
    # truth and still shows the student the filename they uploaded.
    #
    # A web citation has no `document_id` to resolve, and must not be given one —
    # `_citation_out` keeps the two paths apart rather than letting a web result fall
    # through to "unknown document", which would render as a file the student never
    # uploaded and is precisely the confusion the distinguishability criterion
    # forbids.
    filenames = {
        d.id: d.filename
        for d in request.app.state.documents.list_for_session(session.id)
    }

    return QueryResponse(
        answer=answer.text,
        strategy=answer.strategy,
        trace_id=answer.trace_id,
        citations=[_citation_out(c, filenames) for c in answer.citations],
        grounded=answer.grounded,
        latency_ms=answer.latency_ms,
        cost_usd=float(cost),
        prompt_tokens=answer.usage.prompt_tokens,
        completion_tokens=answer.usage.completion_tokens,
    )
