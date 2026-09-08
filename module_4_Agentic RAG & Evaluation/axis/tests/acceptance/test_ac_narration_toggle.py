"""PRD Section 5 — student must-have:

    "I want to toggle the trace between raw and narrated views so that I can
    choose the level of technical detail that matches what I currently understand."

PRD Section 6 acceptance criterion:

    Given a completed trace, when a student toggles to narrated view for the first
    time on a given step, then a plain-language narration is generated and cached;
    when toggled again for the same step, then the cached narration is shown
    without a new LLM call.

Milestone 1.

This criterion is really two requirements wearing one sentence, and the second is
the load-bearing one. "A narration is generated" is ordinary. "Toggled again …
without a new LLM call" is a *cost* requirement: a student flipping between views
while trying to understand a step is the expected behaviour, not an edge case, and
paying for an LLM call on every flip is how a $2 per-student budget disappears.
PRD Section 5 lists the caching separately as a should-have for exactly this
reason.

As with the cap tests, "without a new LLM call" is proven by counting provider
calls, not by comparing response bodies — two identical narrations tell you
nothing about whether the second one was paid for.
"""

from __future__ import annotations

import httpx
import pytest

from ai_backend.contracts.models import AgentStep, StepType

pytestmark = [pytest.mark.story("raw/narrated toggle"), pytest.mark.milestone(1)]


@pytest.fixture
async def recorded_step(session: dict, step_store) -> AgentStep:
    """One completed step, of the kind a student would want explained."""
    step = AgentStep(
        session_id=str(session["session_id"]),
        trace_id="t1",
        step_type=StepType.RETRIEVE,
        label="VectorRetriever.retrieve",
        raw_input="'parental leave', top_k=5",
        raw_output="3 chunks above threshold (0.81, 0.77, 0.71)",
        duration_ms=412,
    )
    await step_store.append(step)
    return step


async def test_first_toggle_generates_a_narration(
    client: httpx.AsyncClient,
    session: dict,
    auth: dict[str, str],
    recorded_step: AgentStep,
    fake_llm,
) -> None:
    session_id = str(session["session_id"])

    response = await client.post(
        f"/api/v1/sessions/{session_id}/trace/{recorded_step.id}/narrate", headers=auth
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["generated"] is True
    assert body["narration"].strip()
    assert fake_llm.call_count == 1, "the first toggle should cost exactly one call"


async def test_second_toggle_makes_no_new_llm_call(
    client: httpx.AsyncClient,
    session: dict,
    auth: dict[str, str],
    recorded_step: AgentStep,
    fake_llm,
) -> None:
    """The clause that matters: flipping back is free."""
    session_id = str(session["session_id"])
    url = f"/api/v1/sessions/{session_id}/trace/{recorded_step.id}/narrate"

    first = await client.post(url, headers=auth)
    assert first.status_code == 200, first.text
    calls_after_first = fake_llm.call_count
    assert calls_after_first == 1

    second = await client.post(url, headers=auth)

    assert second.status_code == 200, second.text
    body = second.json()
    assert body["generated"] is False, "the second toggle should be served from cache"
    assert body["narration"] == first.json()["narration"]
    assert fake_llm.call_count == calls_after_first, (
        "toggling back must not incur another LLM call"
    )


async def test_narration_is_cached_per_step_not_per_trace(
    client: httpx.AsyncClient,
    session: dict,
    auth: dict[str, str],
    step_store,
    fake_llm,
) -> None:
    """Each step is narrated independently.

    Caching at trace granularity would either narrate every step on the first
    toggle — paying for explanations nobody asked for, which is the opposite of
    the lazy design in System Design Section 10 — or serve one step's narration
    for another.
    """
    session_id = str(session["session_id"])
    steps = [
        AgentStep(
            session_id=session_id,
            trace_id="t1",
            step_type=StepType.RETRIEVE,
            label=f"step-{i}",
            raw_output=f"output {i}",
        )
        for i in range(2)
    ]
    for step in steps:
        await step_store.append(step)

    first = await client.post(
        f"/api/v1/sessions/{session_id}/trace/{steps[0].id}/narrate", headers=auth
    )
    assert first.json()["generated"] is True
    assert fake_llm.call_count == 1

    second = await client.post(
        f"/api/v1/sessions/{session_id}/trace/{steps[1].id}/narrate", headers=auth
    )
    assert second.json()["generated"] is True, "a different step needs its own narration"
    assert fake_llm.call_count == 2
    assert second.json()["narration"] != first.json()["narration"]


async def test_narration_never_leaks_a_secret(
    client: httpx.AsyncClient,
    session: dict,
    auth: dict[str, str],
    step_store,
) -> None:
    """Narration is LLM output about traced data, so it is a leak path too.

    System Design Section 6.5 priority 1 says a key must never be written into an
    `AgentStep` shown to students. Narration is generated *from* step content and
    stored back onto the step, so it must pass the same redaction as everything
    else — an easy place to forget, since it is written on a path that runs long
    after the step was first recorded.

    The planted secret matters. An earlier version of this test read the
    configured secrets from settings, which are empty under the fake providers —
    so it passed while asserting nothing, and the strict-xfail marker caught it.
    Planting a key that is definitely present means the test cannot succeed
    vacuously.
    """
    planted = "sk-proj-plantedsecretthatmustnotescape123"
    session_id = str(session["session_id"])

    # A step whose output carries a key — the realistic case being a provider
    # error that echoes the credential back, or an uploaded config file flowing
    # through retrieval into a step.
    leaky = AgentStep(
        session_id=session_id,
        trace_id="t1",
        step_type=StepType.GENERATE,
        label="provider call",
        raw_output=f"401 Unauthorized for key {planted}",
    )
    await step_store.append(leaky)

    response = await client.post(
        f"/api/v1/sessions/{session_id}/trace/{leaky.id}/narrate",
        headers=auth,
    )
    assert response.status_code == 200, response.text
    narration = response.json()["narration"]

    assert narration, "there must be a narration to inspect"
    assert planted not in narration


@pytest.mark.milestone(-1)
async def test_narrating_an_unknown_step_is_a_clean_404(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """Green now: the route, auth, and lookup all exist ahead of generation."""
    response = await client.post(
        f"/api/v1/sessions/{str(session['session_id'])}/trace/nope/narrate", headers=auth
    )

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "not_found"
