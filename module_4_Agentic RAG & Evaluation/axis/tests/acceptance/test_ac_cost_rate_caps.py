"""PRD Section 5 — instructor must-have:

    "I want per-session cost and rate caps so that one runaway agentic loop can't
    exhaust the class's shared budget mid-session."

PRD Section 6 acceptance criterion:

    Given a session has reached its configured cost or request cap, when a new
    query is submitted, then it is rejected with a clear message stating the cap
    was reached, before any LLM call is made.

The second of the two criteria that must pass at Milestone -1.

**How the "before any LLM call" clause is actually tested.** You cannot prove a
call did not happen by reading a response body — a 429 with a helpful message
would look identical whether the cap fired before or after a provider was paid.
So the test registers a stub pipeline that *does* call the LLM, and asserts
`fake_llm.call_count`:

    uncapped session  → 200, call_count == 1   (the LLM is genuinely reachable)
    capped session    → 429, call_count == 0   (the cap fired first)

The first assertion is what stops the second from being vacuous. Without it, a
`call_count == 0` would pass just as happily on a system where nothing calls the
LLM at all — which is exactly the state of the world at Milestone -1, and exactly
the trap this pair of assertions is built to avoid.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from ai_backend.contracts.models import Answer, Message, Role, Strategy
from ai_backend.contracts.pipeline import QueryContext
from ai_backend.pipelines import register, unregister
from ai_backend.providers.fake import FakeLLMProvider

pytestmark = [
    pytest.mark.story("per-session cost/rate caps"),
    pytest.mark.milestone(-1),
]

CAPPED_STRATEGY = Strategy.NAIVE_RAG


class _StubPipeline:
    """The smallest thing that spends money.

    Deliberately not a real strategy: this test is about the Backend's cap
    enforcement, and coupling it to Naive RAG's behaviour would make it fail for
    reasons that have nothing to do with caps once Milestone 0 lands.
    """

    strategy = CAPPED_STRATEGY

    def __init__(self, llm: FakeLLMProvider) -> None:
        self._llm = llm

    async def run(self, ctx: QueryContext) -> Answer:
        completion = await self._llm.complete(
            [Message(role=Role.USER, content=ctx.question)]
        )
        return Answer(
            text=completion.text,
            strategy=ctx.strategy,
            trace_id=ctx.trace_id,
            usage=completion.usage,
        )


@pytest.fixture
def spending_pipeline(fake_llm: FakeLLMProvider) -> Iterator[FakeLLMProvider]:
    """Register a pipeline that calls the LLM, and remove it afterwards."""
    register(CAPPED_STRATEGY, lambda: _StubPipeline(fake_llm))
    try:
        yield fake_llm
    finally:
        unregister(CAPPED_STRATEGY)


async def _ask(client: httpx.AsyncClient, session_id: str, auth: dict[str, str]):
    return await client.post(
        f"/api/v1/sessions/{session_id}/query",
        json={"question": "What is the refund policy?", "strategy": CAPPED_STRATEGY.value},
        headers=auth,
    )


# ---------------------------------------------------------------------------
# The control: the LLM really is reachable through this path.
# ---------------------------------------------------------------------------


async def test_uncapped_query_reaches_the_llm(
    client: httpx.AsyncClient,
    session: dict,
    auth: dict[str, str],
    spending_pipeline: FakeLLMProvider,
) -> None:
    """Without a cap in the way, the query spends money.

    This is the control for every `call_count == 0` assertion below.
    """
    response = await _ask(client, str(session["session_id"]), auth)

    assert response.status_code == 200, response.text
    assert spending_pipeline.call_count == 1, (
        "the stub pipeline must actually call the LLM, or the 'no call was made' "
        "assertions below prove nothing"
    )
    assert response.json()["cost_usd"] > 0


# ---------------------------------------------------------------------------
# The cost cap.
# ---------------------------------------------------------------------------


async def test_cost_cap_rejects_before_any_llm_call(
    client: httpx.AsyncClient,
    session: dict,
    auth: dict[str, str],
    spending_pipeline: FakeLLMProvider,
    spend_to_cap,
) -> None:
    """The criterion, exactly: rejected, with a clear message, and no LLM call."""
    session_id = str(session["session_id"])
    spend_to_cap(session_id)

    response = await _ask(client, session_id, auth)

    # "rejected"
    assert response.status_code == 429, response.text

    body = response.json()
    # "with a clear message stating the cap was reached"
    assert body["code"] == "budget_exceeded", body
    assert "cap" in body["message"].lower(), body["message"]

    # "before any LLM call is made" — the assertion that carries the criterion.
    assert spending_pipeline.call_count == 0, (
        "the cap must be enforced before the provider is reached, not after"
    )


async def test_cost_cap_message_names_the_limit(
    client: httpx.AsyncClient,
    session: dict,
    auth: dict[str, str],
    spending_pipeline: FakeLLMProvider,
    spend_to_cap,
) -> None:
    """The message has to be actionable, not merely correct.

    A student who hits a cap mid-lab needs to know it was a budget limit and that
    a new session is the way forward — otherwise it reads as Axis being broken.
    """
    session_id = str(session["session_id"])
    spend_to_cap(session_id)

    body = (await _ask(client, session_id, auth)).json()

    assert f"{session['cap_cost_usd']:.2f}" in body["message"], body["message"]
    assert "session" in (body.get("detail") or body["message"]).lower()


# ---------------------------------------------------------------------------
# The request cap. A separate cap because it fails differently: it stops a
# student hammering the button even when each individual query is cheap.
# ---------------------------------------------------------------------------


async def test_request_cap_rejects_before_any_llm_call(
    client: httpx.AsyncClient,
    auth: dict[str, str],
    session: dict,
    spending_pipeline: FakeLLMProvider,
) -> None:
    """Once the request count is exhausted, further queries never reach a provider."""
    session_id = str(session["session_id"])
    cap = int(session["cap_requests"])

    for i in range(cap):
        response = await _ask(client, session_id, auth)
        assert response.status_code == 200, f"request {i + 1}/{cap}: {response.text}"

    calls_before = spending_pipeline.call_count
    assert calls_before == cap

    response = await _ask(client, session_id, auth)

    assert response.status_code == 429, response.text
    body = response.json()
    assert body["code"] == "budget_exceeded", body
    assert str(cap) in body["message"], body["message"]
    assert spending_pipeline.call_count == calls_before, (
        "the request cap must reject before the provider is reached"
    )


async def test_a_rejected_query_does_not_change_recorded_spend(
    client: httpx.AsyncClient,
    session: dict,
    auth: dict[str, str],
    spending_pipeline: FakeLLMProvider,
    spend_to_cap,
    backend_app,
) -> None:
    """A refusal costs nothing.

    Follows from "before any LLM call is made", and worth asserting separately: a
    cap that charged for the requests it refused would drift the ledger away from
    the trace a student is looking at.
    """
    session_id = str(session["session_id"])
    spend_to_cap(session_id)
    before = backend_app.state.sessions.get(session_id).spent_usd

    await _ask(client, session_id, auth)

    after = backend_app.state.sessions.get(session_id).spent_usd
    assert after == before


# ---------------------------------------------------------------------------
# Mid-loop exhaustion — Milestone 1.
#
# PRD Section 6's criterion covers query *admission* only: a session already at its
# cap is refused before any call. It says nothing about a cap reached partway
# through a pipeline, because until Milestone 1 no pipeline made more than one call.
#
# The requirement for that case comes from System Design Section 11:
#
#     | Agent hits iteration/tool budget | Trace shows "stopped: budget reached"
#       with partial synthesis |
#
# "Partial synthesis" is the load-bearing phrase. A bounded agent that stops is
# behaving correctly, and rendering that as an error teaches the opposite — the
# whole point of the bound is that hitting it is survivable.
# ---------------------------------------------------------------------------


@pytest.mark.milestone(1)
async def test_a_query_exhausting_its_loop_budget_still_answers(
    client: httpx.AsyncClient,
    session: dict,
    auth: dict[str, str],
) -> None:
    """The agent runs out of iterations and the student still gets an answer.

    The test settings cap the loop at 2 iterations and 4 LLM calls, and no documents
    are uploaded — so every retrieval is empty and the escalation loop is entered
    for the one sub-question, exhausts what it is allowed, and stops.

    What must not happen: a 500, or an empty body. The run is bounded, not broken.
    """
    session_id = str(session["session_id"])

    response = await client.post(
        f"/api/v1/sessions/{session_id}/query",
        json={
            "question": "Compare the leave policy with the remote work policy.",
            "strategy": Strategy.AGENTIC_RAG.value,
        },
        headers=auth,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"].strip(), "a bounded stop must still produce an answer"
    # Nothing was found, so the answer must say so rather than invent a source.
    assert body["grounded"] is False
    assert body["citations"] == []

    steps = (
        await client.get(
            f"/api/v1/sessions/{session_id}/trace/steps",
            params={"trace_id": body["trace_id"]},
            headers=auth,
        )
    ).json()

    # Synthesis is what "partial synthesis" means: the run reached the end.
    assert any(s["step_type"] == "synthesize" for s in steps), [
        s["step_type"] for s in steps
    ]
    # And a bounded stop is never rendered as a failure.
    assert not any(s["status"] == "error" for s in steps), [
        s for s in steps if s["status"] == "error"
    ]


@pytest.mark.milestone(1)
async def test_the_agent_loop_cannot_outspend_the_query_call_budget(
    client: httpx.AsyncClient,
    session: dict,
    auth: dict[str, str],
    fake_llm: FakeLLMProvider,
) -> None:
    """The running-total fix, observed end to end.

    Before Milestone 1 each call was checked against the *whole* remaining
    allowance with nothing decremented, so a pipeline making N calls could pass N
    checks and still exceed the cap. The test settings allow 4 LLM calls per query;
    an agentic run must respect that however hard the loop wants to explore.
    """
    session_id = str(session["session_id"])

    await client.post(
        f"/api/v1/sessions/{session_id}/query",
        json={
            "question": "Compare the leave policy with the remote work policy.",
            "strategy": Strategy.AGENTIC_RAG.value,
        },
        headers=auth,
    )

    assert fake_llm.call_count <= 4, (
        f"the query made {fake_llm.call_count} LLM calls against a cap of 4 — "
        f"the per-query budget is not being enforced cumulatively"
    )
