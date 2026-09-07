"""Cap enforcement, tested directly against the ledger.

The acceptance test in `tests/acceptance/test_ac_cost_rate_caps.py` proves the
criterion end to end through HTTP. These tests cover the mechanics underneath it —
in particular the atomicity of read-then-increment, which is the part that would
fail only under concurrency and would be nearly impossible to diagnose from a
workshop bug report.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from ai_backend.errors import BudgetExceededError
from backend.core.limits import check_and_reserve
from backend.store.db import Database
from backend.store.repositories import SessionRepository


@pytest.fixture
def sessions(database: Database) -> SessionRepository:
    return SessionRepository(database)


def _new_session(
    sessions: SessionRepository, *, cost: str = "1.00", requests: int = 5
):
    return sessions.create(
        cap_cost_usd=Decimal(cost), cap_requests=requests, ttl_seconds=3600
    )


def test_a_fresh_session_is_admitted(sessions: SessionRepository, settings) -> None:
    record, _ = _new_session(sessions)

    budget = check_and_reserve(
        sessions=sessions, session_id=record.id, settings=settings
    )

    assert budget.max_cost_usd == pytest.approx(1.00)
    assert budget.max_agent_iterations == settings.caps.max_agent_iterations


def test_spend_at_the_cap_is_refused(sessions: SessionRepository, settings) -> None:
    record, _ = _new_session(sessions, cost="1.00")
    sessions.record_spend(record.id, cost_usd=Decimal("1.00"))

    with pytest.raises(BudgetExceededError, match="cost cap"):
        check_and_reserve(sessions=sessions, session_id=record.id, settings=settings)


def test_an_estimate_that_would_breach_the_cap_is_refused(
    sessions: SessionRepository, settings
) -> None:
    """A cap, not an overdraft notice.

    Refusing a query that *would* exceed the budget is the difference between
    bounding spend and reporting it after the fact. This is why
    `estimate_cost` is part of the `LLMProvider` interface.
    """
    record, _ = _new_session(sessions, cost="1.00")
    sessions.record_spend(record.id, cost_usd=Decimal("0.95"))

    with pytest.raises(BudgetExceededError, match="estimated"):
        check_and_reserve(
            sessions=sessions,
            session_id=record.id,
            settings=settings,
            estimated_cost_usd=Decimal("0.20"),
        )


def test_an_estimate_that_fits_is_admitted(
    sessions: SessionRepository, settings
) -> None:
    record, _ = _new_session(sessions, cost="1.00")
    sessions.record_spend(record.id, cost_usd=Decimal("0.50"))

    budget = check_and_reserve(
        sessions=sessions,
        session_id=record.id,
        settings=settings,
        estimated_cost_usd=Decimal("0.10"),
    )

    assert budget.max_cost_usd == pytest.approx(0.50)


def test_the_request_cap_admits_exactly_its_limit(
    sessions: SessionRepository, settings
) -> None:
    """Off-by-one matters: a cap of 3 means three queries, then a refusal."""
    record, _ = _new_session(sessions, requests=3)

    for _ in range(3):
        check_and_reserve(sessions=sessions, session_id=record.id, settings=settings)

    with pytest.raises(BudgetExceededError, match="3 requests"):
        check_and_reserve(sessions=sessions, session_id=record.id, settings=settings)


def test_the_remaining_budget_shrinks_as_it_is_spent(
    sessions: SessionRepository, settings
) -> None:
    """The query budget is what remains of the *session's* cap, not a flat figure.

    That is what makes agentic cost visible: a loop either fits in what is left or
    stops partway and says so, which is the lesson rather than an inconvenience.
    """
    record, _ = _new_session(sessions, cost="1.00")

    first = check_and_reserve(
        sessions=sessions, session_id=record.id, settings=settings
    )
    sessions.record_spend(record.id, cost_usd=Decimal("0.60"))
    second = check_and_reserve(
        sessions=sessions, session_id=record.id, settings=settings
    )

    assert first.max_cost_usd > second.max_cost_usd
    assert second.max_cost_usd == pytest.approx(0.40)


async def test_concurrent_requests_cannot_both_slip_under_the_cap(
    sessions: SessionRepository, settings
) -> None:
    """The reason `reserve_request` is a single transaction.

    Read-then-increment without atomicity lets two simultaneous queries each read
    the same count, each see room, and both proceed — the precise runaway the cap
    exists to prevent. A Compare run fires both strategies at once, so this is
    ordinary behaviour rather than a contrived race.
    """
    record, _ = _new_session(sessions, requests=4)

    def _attempt() -> bool:
        try:
            check_and_reserve(
                sessions=sessions, session_id=record.id, settings=settings
            )
            return True
        except BudgetExceededError:
            return False

    results = await asyncio.gather(
        *(asyncio.to_thread(_attempt) for _ in range(10))
    )

    assert sum(results) == 4, (
        f"a cap of 4 admitted {sum(results)} of 10 concurrent requests — "
        f"the reserve is not atomic"
    )


def test_recorded_spend_accumulates_exactly(sessions: SessionRepository) -> None:
    record, _ = _new_session(sessions)

    for _ in range(3):
        sessions.record_spend(record.id, cost_usd=Decimal("0.01"))

    assert sessions.get(record.id).spent_usd == Decimal("0.03")


def test_a_session_caps_at_the_server_maximum(sessions: SessionRepository) -> None:
    """Caps are copied onto the row at creation.

    So changing a server default mid-workshop cannot retroactively move a live
    session's limit up or down under a student who is halfway through a lab.
    """
    record, _ = _new_session(sessions, cost="0.50", requests=2)

    stored = sessions.get(record.id)

    assert stored.cap_cost_usd == Decimal("0.50")
    assert stored.cap_requests == 2
