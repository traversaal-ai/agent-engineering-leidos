"""PRD Section 5 — student must-have:

    "I want to run Compare mode so that I can see latency, cost, and answer
    quality for both strategies side by side on the same question."

PRD Section 6 acceptance criterion:

    Given one question and one document set, when Compare mode is run, then both
    strategies execute and the results table displays latency, token cost, and a
    quality score for each, even if one strategy fails (in which case that
    strategy's column shows the failure, not a blank cell, and the other still
    renders).

This is the criterion the whole platform exists to satisfy — the others are, in a
sense, its preconditions.

**These two tests were strict-xfailed against "all four" and now assert two.** The
xfail reason was that the criterion could not be fully met while half the strategies
were unbuilt. They are cancelled rather than unbuilt now (PRD Section 3), so the
criterion is met at its real scope and the xfails are gone.

Two clauses drive the tests, and the second is the one that will actually be
exercised in a classroom:

**"even if one strategy fails … the other still renders."** Non-determinism and
provider rate limits (PRD Section 7) make a partial failure the *likely* case across a
workshop's worth of Compare runs, not the exceptional one. With only two columns this
matters more, not less: a dashboard that renders nothing when one fails leaves a class
with no comparison at all.

**Goal 2's 45-second budget.** The strategies run concurrently or the target is
unreachable, so there is a test asserting they overlap rather than queue.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from ai_backend.contracts.models import Answer, Strategy
from ai_backend.contracts.pipeline import QueryContext
from ai_backend.errors import ProviderError
from ai_backend.pipelines import _registry, mark_unavailable, register, unregister
from tests.docfixtures import make_pdf

pytestmark = [pytest.mark.story("compare mode"), pytest.mark.milestone(3)]

EVERY_STRATEGY = [s.value for s in Strategy]

_POLICY = "Parental leave is 16 weeks of paid time off, taken within the first year."


async def _compare(client: httpx.AsyncClient, session: dict, auth: dict[str, str]):
    """One Compare run over one indexed document. Shared by the two tests below."""
    await client.post(
        f"/api/v1/sessions/{str(session['session_id'])}/documents",
        files=[("files", ("policy.pdf", make_pdf(_POLICY), "application/pdf"))],
        headers=auth,
    )
    response = await client.post(
        "/api/v1/compare",
        json={"question": "How does leave interact with the remote work policy?"},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_every_strategy_reports_latency_and_cost(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """Two of the three columns the criterion names, on every row.

    Asserted against the enum rather than a literal pair, so adding a strategy without
    giving it these columns fails here. The third column — `quality_score` — is not
    computed; see the xfail below rather than folding it in and losing these.
    """
    body = await _compare(client, session, auth)

    assert {r["strategy"] for r in body["results"]} == set(EVERY_STRATEGY)
    for result in body["results"]:
        assert result["status"] == "ok", result
        assert result["latency_ms"] > 0, result
        assert result["cost_usd"] > 0, result


@pytest.mark.xfail(
    strict=True,
    reason="quality_score is not computed: the compare endpoint has no scorer wired in",
)
async def test_every_strategy_reports_a_quality_score(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """The third column the criterion names, and the one genuinely not built.

    **Split out of the test above, and the split is the point.** The two were one
    strict-xfailed test whose stated reason was that half the strategies did not exist.
    They exist now, so that reason is void — but the criterion is still not fully met,
    for a completely different and much narrower cause: `_to_result` never populates
    `quality_score`, because no scorer is wired into the compare endpoint. The
    evaluation harness scores answers offline (`ai_backend/evaluation/scoring.py`) and
    nothing connects it to this response.

    Kept strict so that wiring one in turns this green loudly, and kept separate so
    that the latency and cost assertions — which do pass — are not hidden behind it.
    Honest xfail reasons matter: the old one would have had a reader looking for
    unbuilt strategies rather than a missing scorer.
    """
    body = await _compare(client, session, auth)

    for result in body["results"]:
        assert result["quality_score"] is not None, result


async def test_one_failing_strategy_does_not_blank_the_table(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """The clause that will matter most in practice.

    One strategy is made to fail deliberately; the other must still render with full
    metrics, and the failing one must show *why* rather than showing nothing. A blank
    cell teaches nothing; a visible failure is itself a lesson.

    **The baseline is the one broken here, on purpose.** This test used to break a
    strategy nobody had built, which made it a test of a stub rather than of the
    endpoint's behaviour under a real failure. Substituting a broken pipeline for
    Naive RAG exercises the same path the classroom actually hits — a provider error
    mid-run — and the original factory is restored afterwards so the surrounding
    suite is untouched.
    """
    broken_for = Strategy.NAIVE_RAG
    survivor = Strategy.AGENTIC_RAG

    class _BrokenPipeline:
        strategy = broken_for

        async def run(self, ctx: QueryContext) -> Answer:
            raise ProviderError("The embedding provider returned HTTP 503.")

    original = _registry[broken_for]
    register(broken_for, _BrokenPipeline)
    try:
        response = await client.post(
            "/api/v1/compare", json={"question": "Anything?"}, headers=auth
        )
    finally:
        register(broken_for, original)

    assert response.status_code == 200, (
        "one broken strategy must not fail the whole comparison"
    )
    results = {r["strategy"]: r for r in response.json()["results"]}
    assert set(results) == set(EVERY_STRATEGY), "every strategy must appear"

    broken = results[broken_for.value]
    assert broken["status"] == "error"
    assert broken["error"], "the failing column must show the failure, not a blank cell"

    assert results[survivor.value]["status"] == "ok", (
        f"{survivor.value} should still render: {results[survivor.value]}"
    )


# Green at Milestone -1, not Milestone 3. The strict-xfail marker this test
# originally carried failed the build to say so: the Compare endpoint's
# orchestration exists now, and this test brings its own stub pipelines, so it
# needs none of the real four. Locking concurrency in *before* the strategies
# arrive is the point — Goal 2's 45-second budget is unreachable if the four ever
# start queueing, and that regression is far cheaper to catch here than at
# Milestone 3 with real pipelines obscuring the cause.
@pytest.mark.milestone(-1)
async def test_strategies_run_concurrently(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """PRD Goal 2: both strategies inside the 45-second budget.

    Two strategies that each take `delay_ms` must finish in about `delay_ms`, not twice
    it. Asserted as a wall-clock bound against a known per-strategy delay, which is the
    observable difference between `gather` and a for-loop.

    **The bound is derived, not hand-picked, and that matters.** It was a fixed
    `delay_ms * 2.5`, chosen when four strategies made sequential execution ~4x the
    delay. With two, sequential is only 2x — comfortably *inside* that bound, so the
    test would have passed a fully sequential Compare endpoint and reported nothing.
    Halving the strategy count silently disarmed it. Computing the threshold from
    `len(Strategy)` keeps it honest at any count: it sits midway between concurrent
    (~1x) and sequential (~Nx), so it can only be met by real overlap.
    """
    delay_ms = 400
    sequential_ms = delay_ms * len(Strategy)
    # Midway between concurrent and sequential, with the floor covering the degenerate
    # single-strategy case where the two are indistinguishable by timing alone.
    budget_ms = max(delay_ms * 1.6, (delay_ms + sequential_ms) / 2)

    def _slow(strategy: Strategy):
        class _SlowPipeline:
            def __init__(self) -> None:
                self.strategy = strategy

            async def run(self, ctx: QueryContext) -> Answer:
                await asyncio.sleep(delay_ms / 1000)
                return Answer(text="ok", strategy=strategy, trace_id=ctx.trace_id)

        return _SlowPipeline

    # Saved and restored rather than unregistered. Every member is a real pipeline now,
    # so unregistering them all would leave the registry empty for whatever runs next —
    # it only ever worked because two of the four slots were empty to begin with.
    originals = {s: _registry[s] for s in Strategy if s in _registry}
    for strategy in Strategy:
        register(strategy, _slow(strategy))
    try:
        loop = asyncio.get_running_loop()
        started = loop.time()
        response = await client.post(
            "/api/v1/compare", json={"question": "Anything?"}, headers=auth
        )
        elapsed_ms = (loop.time() - started) * 1000
    finally:
        for strategy in Strategy:
            unregister(strategy)
        for strategy, factory in originals.items():
            register(strategy, factory)

    assert response.status_code == 200, response.text
    assert elapsed_ms < budget_ms, (
        f"{len(Strategy)} strategies took {elapsed_ms:.0f}ms for a {delay_ms}ms task "
        f"each (sequential would be ~{sequential_ms}ms, budget {budget_ms:.0f}ms) — "
        f"they appear to be running sequentially"
    )


# Also green at Milestone -1: persistence does not depend on any strategy
# succeeding. A run in which every strategy is unavailable still has metrics worth
# keeping, which is exactly what makes a partial failure renderable.
@pytest.mark.milestone(-1)
async def test_a_comparison_run_is_persisted(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str], backend_app
) -> None:
    """PRD Section 5 nice-to-have (export a run) depends on this being stored.

    Also what Goal 5's cross-class aggregate view would read, so the metrics need
    to survive the request that produced them.
    """
    body = (
        await client.post(
            "/api/v1/compare", json={"question": "Anything?"}, headers=auth
        )
    ).json()

    stored = backend_app.state.comparisons.get_metrics(body["comparison_run_id"])
    assert stored, "the comparison run's metrics were not persisted"
    assert "per_strategy" in stored


@pytest.mark.milestone(0)
async def test_compare_distinguishes_unavailable_strategies_from_broken_ones(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """A strategy that *cannot run here* reports "unavailable", not "error".

    Three outcomes, three meanings, and collapsing any two of them misleads a class:
    `ok` is a run, `error` is a run that broke, and `unavailable` is a run that never
    started because this configuration cannot do it. A student who sees "error" where
    the truth is "your provider cannot call tools" goes looking for a bug in Axis.

    **Repurposed rather than deleted.** This test used to prove the point with the two
    unbuilt graph quadrants, which no longer exist — but the `unavailable` status is not
    theirs, it belongs to `mark_unavailable`, and that fires for a reason a workshop
    genuinely hits: an LLM provider whose adapter cannot call tools. Testing it that way
    round is strictly better, because it is the case someone will actually meet.
    """
    unavailable_for = Strategy.AGENTIC_RAG
    reason = "AXIS_LLM__PROVIDER='ollama' cannot call tools."

    await client.post(
        f"/api/v1/sessions/{str(session['session_id'])}/documents",
        files=[("files", ("policy.pdf", make_pdf(_POLICY), "application/pdf"))],
        headers=auth,
    )

    original = _registry[unavailable_for]
    mark_unavailable(unavailable_for, reason)
    try:
        response = await client.post(
            "/api/v1/compare",
            json={"question": "How long is parental leave?"},
            headers=auth,
        )
    finally:
        register(unavailable_for, original)

    assert response.status_code == 200, response.text
    results = {r["strategy"]: r for r in response.json()["results"]}
    assert set(results) == set(EVERY_STRATEGY), (
        "every strategy must appear, runnable or not"
    )

    runnable = results[Strategy.NAIVE_RAG.value]
    assert runnable["status"] == "ok", runnable
    assert runnable["latency_ms"] >= 0
    assert runnable["cost_usd"] > 0, "a real naive_rag run costs something"

    cell = results[unavailable_for.value]
    assert cell["status"] == "unavailable", cell
    assert cell["error"], "an unavailable strategy must explain itself"
    assert "cannot call tools" in cell["error"], (
        f"the explanation must be the configured reason, not a generic one: {cell}"
    )
