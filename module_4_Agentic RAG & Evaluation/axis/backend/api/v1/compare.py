"""POST /api/v1/compare — one question, both strategies.

Two properties of this endpoint constrain everything built before it.

**Strategies run concurrently.** PRD Section 2 targets under 45 seconds. Run
sequentially, an agentic run that takes twelve seconds is added to the baseline's;
run concurrently, the slower one sets the pace. `asyncio.gather` is why every provider
and retriever interface in `contracts/` is async.

**A failure fills its column rather than emptying the table.** Per PRD Section 6, when
one strategy fails "that strategy's column shows the failure, not a blank cell, and the
other still renders". Hence `return_exceptions=True` and a per-strategy status — a
broken strategy is itself a teaching moment, and losing the working one to it would be
the worst possible outcome in front of a class.
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal

from fastapi import APIRouter, Depends, Request

from ai_backend.config.settings import Settings
from ai_backend.contracts.models import Answer, Strategy
from ai_backend.errors import AxisError, BudgetExceededError, UnsupportedStrategyError
from backend import dispatch
from backend.api.v1.query import _citation_out
from backend.core.auth import require_session
from backend.core.limits import check_and_reserve
from backend.schemas.compare import CompareRequest, CompareResponse, StrategyResult
from backend.store.repositories import SessionRecord

router = APIRouter(tags=["compare"])


@router.post("/compare", response_model=CompareResponse)
async def compare(
    body: CompareRequest,
    request: Request,
    session: SessionRecord = Depends(require_session),
) -> CompareResponse:
    settings: Settings = request.app.state.settings
    sessions = request.app.state.sessions
    comparisons = request.app.state.comparisons

    targets = body.strategies or list(Strategy)

    # One cap check for the whole comparison, before any strategy starts. A
    # Compare run is the most expensive thing a student can do — both strategies,
    # one of them an agent loop — so it is exactly what the cap exists to bound.
    budget = check_and_reserve(
        sessions=sessions,
        session_id=session.id,
        settings=settings,
        estimated_cost_usd=None,
    )

    run_id = comparisons.create(session_id=session.id, question=body.question)

    started = time.perf_counter()
    outcomes = await asyncio.gather(
        *(
            dispatch.run_query(
                session_id=session.id,
                question=body.question,
                strategy=strategy,
                budget=budget,
                corpus=body.corpus,
            )
            for strategy in targets
        ),
        # Never let one failing strategy take down the other.
        return_exceptions=True,
    )
    total_latency_ms = int((time.perf_counter() - started) * 1000)

    results = [
        _to_result(strategy, outcome) for strategy, outcome in zip(targets, outcomes, strict=True)
    ]

    total_cost = sum((Decimal(str(r.cost_usd)) for r in results), Decimal("0"))
    if total_cost:
        sessions.record_spend(session.id, cost_usd=total_cost)

    comparisons.set_metrics(
        run_id,
        {
            "total_latency_ms": total_latency_ms,
            "total_cost_usd": str(total_cost),
            "per_strategy": {r.strategy.value: r.model_dump(mode="json") for r in results},
        },
    )

    return CompareResponse(
        comparison_run_id=run_id,
        question=body.question,
        results=results,
        total_latency_ms=total_latency_ms,
        total_cost_usd=float(total_cost),
    )


def _to_result(strategy: Strategy, outcome: Answer | BaseException) -> StrategyResult:
    """Turn one strategy's outcome — answer or exception — into a table cell.

    The status vocabulary distinguishes three kinds of "no answer" that mean
    genuinely different things to a student: this configuration cannot run the strategy
    (`unavailable`), it stopped because we told it to (`budget_exceeded`), or it
    broke (`error`).

    **`detail` is carried, not just `message`.** For `unavailable` in particular the
    message is generic — "cannot run with the current configuration" — and the *reason*
    lives in the detail: which provider, which environment variable to change. Dropping
    it left the one status a student can actually act on as the least informative cell
    in the table, which inverts Section 11's requirement that a failure be visible.
    """
    if isinstance(outcome, Answer):
        return StrategyResult(
            strategy=strategy,
            status="ok",
            answer=outcome.text,
            trace_id=outcome.trace_id,
            # Through the same helper the query route uses, so a web citation cannot
            # come out looking like a document one in the table where the two are
            # being compared. Filenames are not resolved here — Compare runs across
            # strategies rather than for one session's document list — so a document
            # citation keeps whatever name it arrived with.
            citations=[_citation_out(c, {}) for c in outcome.citations],
            latency_ms=outcome.latency_ms,
            cost_usd=float(outcome.usage.cost_usd),
        )

    if isinstance(outcome, UnsupportedStrategyError):
        return StrategyResult(
            strategy=strategy, status="unavailable", error=_why(outcome)
        )
    if isinstance(outcome, BudgetExceededError):
        return StrategyResult(
            strategy=strategy, status="budget_exceeded", error=_why(outcome)
        )
    if isinstance(outcome, AxisError):
        return StrategyResult(strategy=strategy, status="error", error=_why(outcome))

    # An unexpected exception type. Reported as an error with its class name
    # rather than its text: an arbitrary exception can carry anything, and this
    # table may be on a projector.
    return StrategyResult(
        strategy=strategy,
        status="error",
        error=f"Unexpected {type(outcome).__name__} while running this strategy.",
    )


def _why(exc: AxisError) -> str:
    """The message, plus the detail when there is one.

    An `AxisError`'s detail is the actionable half — which setting, which limit — and
    the cell in this table is the only place a Compare reader sees it. Joined rather
    than nested because `StrategyResult.error` is one string rendered into one cell.
    """
    detail = (exc.detail or "").strip()
    return f"{exc.message} {detail}".strip() if detail else exc.message
