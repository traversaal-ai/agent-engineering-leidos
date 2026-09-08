"""PRD Section 5 — student must-have:

    "I want to choose a strategy (Naive RAG or Agentic RAG) so that I can see how
    each behaves on the same question."

PRD Section 6 acceptance criterion:

    Given an uploaded document set, when a student selects either strategy and
    submits a question, then the response is generated using only that strategy's
    pipeline, and the trace records which strategy was used.

Parametrized over the enum rather than a hand-written list, so a strategy cannot be
added without these tests covering it.

**"using only that strategy's pipeline" is the demanding clause**, and what it guards
is the baseline. Both strategies share one retriever and one index, so the only thing
keeping them distinguishable is that Naive RAG never routes, never decomposes and never
reaches the web. A baseline that quietly acquired any of those would make every Compare
run a lie while every test on answer content still passed —
`test_strategy_emits_the_step_types_its_shape_implies` is the assertion with teeth.
"""

from __future__ import annotations

import httpx
import pytest

from ai_backend.contracts.models import Strategy

pytestmark = pytest.mark.story("choose a strategy")

# The milestone each strategy landed at, used only to tag the cases so
# `--milestone N` can select a slice of the suite. Both are built.
_SCHEDULE: dict[Strategy, int] = {
    Strategy.NAIVE_RAG: 0,
    Strategy.AGENTIC_RAG: 1,
}

_STRATEGY_CASES = [
    pytest.param(strategy, marks=[pytest.mark.milestone(milestone)], id=strategy.value)
    for strategy, milestone in _SCHEDULE.items()
]

# Every member is covered. This is the guard that made the enum and the parametrization
# agree while two declared strategies had no pipeline; it is cheap to keep, and it fails
# loudly if a member is ever added without a case here.
assert set(_SCHEDULE) == set(Strategy), "every Strategy needs a case in _SCHEDULE"


@pytest.mark.parametrize("strategy", _STRATEGY_CASES)
async def test_selected_strategy_answers_and_is_recorded_in_the_trace(
    client: httpx.AsyncClient,
    session: dict,
    auth: dict[str, str],
    strategy: Strategy,
) -> None:
    session_id = str(session["session_id"])

    response = await client.post(
        f"/api/v1/sessions/{session_id}/query",
        json={"question": "What is the parental leave policy?", "strategy": strategy.value},
        headers=auth,
    )

    assert response.status_code == 200, response.text
    body = response.json()

    # The response is attributed to the strategy that was asked for.
    assert body["strategy"] == strategy.value
    assert body["answer"].strip()

    # "the trace records which strategy was used" — checked on the trace itself,
    # not just echoed back in the response envelope. The trace is what Compare
    # mode and the evaluation harness read, so that is where the attribution has
    # to be correct.
    steps = await client.get(
        f"/api/v1/sessions/{session_id}/trace/steps",
        params={"trace_id": body["trace_id"]},
        headers=auth,
    )
    assert steps.status_code == 200, steps.text
    recorded = steps.json()
    assert recorded, "the run produced no trace steps"
    assert {s["strategy"] for s in recorded} == {strategy.value}


@pytest.mark.parametrize("strategy", _STRATEGY_CASES)
async def test_strategy_emits_the_step_types_its_shape_implies(
    client: httpx.AsyncClient,
    session: dict,
    auth: dict[str, str],
    strategy: Strategy,
) -> None:
    """"generated using only that strategy's pipeline", read through the trace.

    The orchestration is observable in the step types. A single-shot strategy must
    *not* emit route/decompose steps, and an agentic one must. If a naive
    pipeline started routing, or an agentic one stopped, the comparison the
    platform teaches would be measuring something other than what it claims.
    """
    session_id = str(session["session_id"])
    body = (
        await client.post(
            f"/api/v1/sessions/{session_id}/query",
            json={"question": "Compare the two policies.", "strategy": strategy.value},
            headers=auth,
        )
    ).json()

    steps = (
        await client.get(
            f"/api/v1/sessions/{session_id}/trace/steps",
            params={"trace_id": body["trace_id"]},
            headers=auth,
        )
    ).json()
    kinds = {s["step_type"] for s in steps}

    # Every strategy retrieves and synthesises.
    assert "retrieve" in kinds, kinds
    assert "synthesize" in kinds, kinds

    if strategy.is_agentic:
        assert "route" in kinds, f"{strategy.value} should route: {kinds}"
        assert "decompose" in kinds, f"{strategy.value} should decompose: {kinds}"
    else:
        assert "route" not in kinds, f"{strategy.value} is single-shot: {kinds}"
        assert "decompose" not in kinds, f"{strategy.value} is single-shot: {kinds}"


@pytest.mark.milestone(-1)
async def test_a_strategy_unavailable_in_this_configuration_says_why(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """A strategy that cannot run here is a clear refusal naming the fix, not a 500.

    **This is the real 501 path, and the only one left.** It used to be reached by
    asking for a declared-but-unbuilt strategy; both are built now, so the surviving
    case is the one that actually happens in a workshop: an LLM provider whose adapter
    cannot call tools leaves Agentic RAG `mark_unavailable`, because an agent loop with
    no tools is Naive RAG with extra steps and presenting it as agentic would break the
    one comparison this platform teaches.

    The refusal has to carry the *reason* rather than just the status. A student told
    only "unavailable" goes looking for a bug; one told which environment variable to
    change fixes it in a minute.
    """
    from ai_backend.pipelines import mark_unavailable, register

    reason = "AXIS_LLM__PROVIDER='ollama' cannot call tools. Use openai or anthropic."
    factory = get_pipeline_factory(Strategy.AGENTIC_RAG)
    mark_unavailable(Strategy.AGENTIC_RAG, reason)
    try:
        response = await client.post(
            f"/api/v1/sessions/{str(session['session_id'])}/query",
            json={"question": "Anything?", "strategy": Strategy.AGENTIC_RAG.value},
            headers=auth,
        )
    finally:
        register(Strategy.AGENTIC_RAG, factory)

    assert response.status_code == 501, response.text
    body = response.json()
    assert body["code"] == "unsupported_strategy"
    detail = body.get("detail") or ""
    assert "cannot call tools" in detail, detail
    assert "AXIS_LLM__PROVIDER" in detail, (
        f"the refusal must name the setting to change: {detail}"
    )


def get_pipeline_factory(strategy: Strategy):
    """The registered factory, so a test can put it back.

    Reaches into `_registry` deliberately: `mark_unavailable` pops the entry, and
    restoring it needs the original factory rather than a rebuilt one — a rebuilt
    pipeline would hold different provider instances and quietly break the call-count
    assertions in every test that runs after this one.
    """
    from ai_backend.pipelines import _registry

    return _registry[strategy]


@pytest.mark.milestone(-1)
async def test_an_unknown_strategy_name_is_rejected(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """Only the two exist. A typo is a validation error, not a new strategy.

    Note which status this is: a name outside the enum is a **400** from Pydantic at
    the request boundary, not the 501 above. `lightrag` is now one of these — it names
    nothing, so it is rejected as malformed rather than reported as missing.
    """
    response = await client.post(
        f"/api/v1/sessions/{str(session['session_id'])}/query",
        json={"question": "Anything?", "strategy": "super_rag"},
        headers=auth,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "invalid_request"
