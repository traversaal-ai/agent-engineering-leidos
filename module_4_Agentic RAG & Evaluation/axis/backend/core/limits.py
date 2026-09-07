"""Per-session cost and rate caps.

PRD Section 5 calls this out as an instructor must-have, and System Design
Section 6.5 ranks it the second-most-important control in the system. Section 6's
acceptance criterion is precise about the ordering, and the ordering is the whole
point:

    Given a session has reached its configured cost or request cap, when a new
    query is submitted, then it is rejected with a clear message stating the cap
    was reached, BEFORE any LLM call is made.

So enforcement lives here, in the Backend, in front of the dispatch into the AI
Backend — not inside a pipeline where it would run after a provider had already
been reached. `tests/acceptance/test_ac_cost_rate_caps.py` proves the ordering by
asserting the fake provider's `call_count` is still zero after a rejection, which
is the only way to test a negative like "no call was made".

Two caps, because they fail differently. The cost cap stops a budget draining; the
request cap stops a student hammering the button even if each query is cheap.
"""

from __future__ import annotations

from decimal import Decimal

from ai_backend.config.settings import Settings
from ai_backend.contracts.pipeline import QueryBudget
from ai_backend.errors import BudgetExceededError
from backend.store.repositories import SessionRecord, SessionRepository


def check_and_reserve(
    *,
    sessions: SessionRepository,
    session_id: str,
    settings: Settings,
    estimated_cost_usd: Decimal | None = None,
) -> QueryBudget:
    """Admit or refuse one query, and return the budget it may spend.

    Raises `BudgetExceededError` before returning if any cap is already reached.
    Whatever happens, no provider has been touched: this function has no access
    to one.

    `estimated_cost_usd` is the pre-call estimate from
    `LLMProvider.estimate_cost`, when the caller has one. Checking it lets a query
    be refused because it *would* breach the cap, rather than only once it
    already has — the difference between a cap and an overdraft notice.
    """
    record = sessions.reserve_request(session_id)

    _assert_requests_available(record)
    _assert_cost_available(record, estimated_cost_usd)

    return _budget_for(record, settings)


def _assert_requests_available(record: SessionRecord) -> None:
    # `reserve_request` has already counted this query, so the cap is breached
    # when the post-increment count *exceeds* it.
    if record.request_count > record.cap_requests:
        raise BudgetExceededError(
            f"This session has reached its limit of {record.cap_requests} requests.",
            detail=(
                "Per-session caps keep one runaway loop from exhausting the "
                "class's shared budget. Start a new session to continue."
            ),
        )


def _assert_cost_available(
    record: SessionRecord, estimated_cost_usd: Decimal | None
) -> None:
    if record.spent_usd >= record.cap_cost_usd:
        raise BudgetExceededError(
            f"This session has reached its cost cap of "
            f"${record.cap_cost_usd:.2f} (spent ${record.spent_usd:.4f}).",
            detail=(
                "No LLM call was made for this request. Start a new session to "
                "continue."
            ),
        )

    if estimated_cost_usd is not None:
        projected = record.spent_usd + estimated_cost_usd
        if projected > record.cap_cost_usd:
            raise BudgetExceededError(
                f"This query is estimated to cost ${estimated_cost_usd:.4f}, "
                f"which would take the session past its ${record.cap_cost_usd:.2f} "
                f"cap (${record.spent_usd:.4f} already spent).",
                detail=(
                    "The estimate assumes the answer runs to its maximum length, "
                    "so it is deliberately pessimistic. A shorter question, or a "
                    "new session, will get through."
                ),
            )


def _budget_for(record: SessionRecord, settings: Settings) -> QueryBudget:
    """What this query is allowed to spend.

    The cost allowance is what remains of the *session's* cap, not a per-query
    figure. That is what makes an agentic loop's cost visible: it either fits in
    what is left or it stops partway and says so, which is the lesson.
    """
    caps = settings.caps
    return QueryBudget(
        max_cost_usd=float(record.remaining_usd),
        max_llm_calls=caps.max_llm_calls_per_query,
        max_agent_iterations=caps.max_agent_iterations,
        max_tool_calls=caps.max_tool_calls_per_query,
        max_search_calls=caps.max_search_calls_per_query,
    )
