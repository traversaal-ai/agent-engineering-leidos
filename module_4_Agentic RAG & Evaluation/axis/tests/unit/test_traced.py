"""The `@traced` decorator and the step-store contract.

The observability library is the Milestone -1 deliverable everything later depends
on, so these tests cover the behaviours that would be expensive to discover later:
that a failing call still leaves a step behind, that nesting produces a tree, and
that cost lands on the step that incurred it.
"""

from __future__ import annotations

import time
from decimal import Decimal

import pytest

from ai_backend.contracts.models import (
    Completion,
    StepStatus,
    StepType,
    Strategy,
    Usage,
)
from ai_backend.errors import BudgetExceededError, ProviderError
from ai_backend.observability import (
    InMemoryStepStore,
    atrace_step,
    child_of,
    trace_context,
    traced,
)
from ai_backend.observability import trace as trace_module


@pytest.fixture
def store() -> InMemoryStepStore:
    fresh = InMemoryStepStore()
    previous = trace_module.get_store()
    trace_module.configure(store=fresh)
    yield fresh
    trace_module.configure(store=previous)


async def test_a_successful_call_records_one_ok_step(store: InMemoryStepStore) -> None:
    @traced(StepType.RETRIEVE, label="probe")
    async def retrieve(query: str) -> str:
        return f"found: {query}"

    with trace_context(session_id="s1", trace_id="t1", strategy=Strategy.NAIVE_RAG):
        result = await retrieve("leave policy")

    assert result == "found: leave policy"
    (step,) = store.all_steps
    assert step.step_type is StepType.RETRIEVE
    assert step.status is StepStatus.OK
    assert step.label == "probe"
    assert step.session_id == "s1"
    assert step.trace_id == "t1"
    assert step.strategy is Strategy.NAIVE_RAG
    assert "leave policy" in (step.raw_input or "")
    assert "found" in (step.raw_output or "")


async def test_a_failing_call_records_the_failure_and_re_raises(
    store: InMemoryStepStore,
) -> None:
    """System Design Section 11: failures must be visible, not silent.

    Both halves matter. Swallowing the exception would make the trace lie, and
    recording nothing would leave a student staring at a gap where the
    interesting thing happened.
    """

    @traced(StepType.GENERATE)
    async def broken() -> None:
        raise ProviderError("upstream exploded")

    with trace_context(session_id="s1", trace_id="t1"), pytest.raises(ProviderError):
        await broken()

    (step,) = store.all_steps
    assert step.status is StepStatus.ERROR
    assert "upstream exploded" in (step.error or "")


async def test_a_budget_stop_is_distinguished_from_an_error(
    store: InMemoryStepStore,
) -> None:
    """"stopped: budget reached" is not a crash.

    The UI renders the two differently (amber, not red), and conflating them
    would teach students that bounding an agent is a malfunction.
    """

    @traced(StepType.CALL_TOOL)
    async def over_budget() -> None:
        raise BudgetExceededError("tool budget reached")

    with trace_context(session_id="s1", trace_id="t1"), pytest.raises(BudgetExceededError):
        await over_budget()

    (step,) = store.all_steps
    assert step.status is StepStatus.BUDGET_EXCEEDED
    assert step.status is not StepStatus.ERROR


async def test_usage_is_lifted_off_the_result(store: InMemoryStepStore) -> None:
    """Cost lands on the step that incurred it, with no call-site bookkeeping.

    This is what makes the two strategies comparable by construction: a pipeline
    author cannot forget to report cost, because they were never asked to.
    """

    @traced(StepType.GENERATE)
    async def generate() -> Completion:
        return Completion(
            text="hello",
            model="fake-model",
            usage=Usage(
                prompt_tokens=100, completion_tokens=20, cost_usd=Decimal("0.0016")
            ),
        )

    with trace_context(session_id="s1", trace_id="t1"):
        await generate()

    (step,) = store.all_steps
    assert step.usage.prompt_tokens == 100
    assert step.usage.completion_tokens == 20
    assert step.usage.cost_usd == Decimal("0.0016")


async def test_nested_calls_produce_a_tree(store: InMemoryStepStore) -> None:
    """A child step records its parent automatically.

    The decorated body runs inside `child_of(step.id)`, so an inner traced call
    is attributed without either function knowing about the other.
    """

    @traced(StepType.RETRIEVE, label="inner")
    async def inner() -> str:
        return "chunks"

    @traced(StepType.CALL_TOOL, label="outer")
    async def outer() -> str:
        return await inner()

    with trace_context(session_id="s1", trace_id="t1"):
        await outer()

    by_label = {s.label: s for s in store.all_steps}
    assert by_label["outer"].parent_step_id is None
    assert by_label["inner"].parent_step_id == by_label["outer"].id


async def test_a_sync_function_can_be_traced(store: InMemoryStepStore) -> None:
    """Chunkers and parsers are synchronous; they should still be traceable."""

    @traced(StepType.INGEST, label="chunk")
    def chunk(text: str) -> list[str]:
        return text.split()

    with trace_context(session_id="s1", trace_id="t1"):
        assert chunk("a b c") == ["a", "b", "c"]

    # The sync path schedules its write on the running loop.
    import asyncio

    await asyncio.sleep(0)
    labels = [s.label for s in store.all_steps]
    assert "chunk" in labels


async def test_output_capture_can_be_disabled(store: InMemoryStepStore) -> None:
    """Embedding vectors would flood the trace and teach nothing."""

    @traced(StepType.EMBED, capture_output=False)
    async def embed() -> list[float]:
        return [0.1] * 1536

    with trace_context(session_id="s1", trace_id="t1"):
        await embed()

    (step,) = store.all_steps
    assert step.raw_output is None


async def test_large_payloads_are_truncated(store: InMemoryStepStore) -> None:
    """The trace is read by humans and exported into reports.

    An unbounded blob would make it unreadable and would balloon the SQLite file
    across a workshop.
    """

    @traced(StepType.SYNTHESIZE)
    async def verbose() -> str:
        return "x" * (trace_module.MAX_PAYLOAD_CHARS + 5_000)

    with trace_context(session_id="s1", trace_id="t1"):
        await verbose()

    (step,) = store.all_steps
    assert step.raw_output is not None
    assert len(step.raw_output) < trace_module.MAX_PAYLOAD_CHARS + 200
    assert "omitted" in step.raw_output


async def test_tracing_outside_a_context_fails_loudly(store: InMemoryStepStore) -> None:
    """A step with no session could not be shown to anyone.

    Better to fail at the call site with an explanation than to silently drop the
    observation, which would show up much later as an inexplicably empty trace.
    """

    @traced(StepType.RETRIEVE)
    async def orphan() -> str:
        return "x"

    with pytest.raises(RuntimeError, match="No active trace context"):
        await orphan()


async def test_trace_step_context_manager_records_handle_output(
    store: InMemoryStepStore,
) -> None:
    """`atrace_step` covers regions the decorator cannot reach — a ReAct iteration."""
    with trace_context(session_id="s1", trace_id="t1"):
        async with atrace_step(
            StepType.ROUTE, label="router", raw_input="a question"
        ) as handle:
            handle.set_output("chose: graph")
            handle.add_usage(Usage(prompt_tokens=10, cost_usd=Decimal("0.001")))
            handle.set_attribute("confidence", 0.82)

    (step,) = store.all_steps
    assert step.step_type is StepType.ROUTE
    assert step.raw_output == "chose: graph"
    assert step.usage.cost_usd == Decimal("0.001")
    assert step.attributes["confidence"] == 0.82


async def test_a_store_failure_does_not_break_the_traced_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recording an observation must never fail the thing being observed.

    During a live demo a broken store should cost the trace pane, not the answer
    on screen.
    """

    class _BrokenStore(InMemoryStepStore):
        async def append(self, step) -> None:  # type: ignore[override]
            raise RuntimeError("disk full")

    previous = trace_module.get_store()
    trace_module.configure(store=_BrokenStore())
    try:

        @traced(StepType.RETRIEVE)
        async def works() -> str:
            return "still fine"

        with trace_context(session_id="s1", trace_id="t1"):
            assert await works() == "still fine"
    finally:
        trace_module.configure(store=previous)


async def test_explicit_child_of_nests_under_a_chosen_step(
    store: InMemoryStepStore,
) -> None:
    with trace_context(session_id="s1", trace_id="t1"):

        @traced(StepType.RETRIEVE, label="nested")
        async def nested() -> str:
            return "x"

        with child_of("iteration-7"):
            await nested()

    (step,) = store.all_steps
    assert step.parent_step_id == "iteration-7"


# ---------------------------------------------------------------------------
# Running steps — what makes a run watchable
# ---------------------------------------------------------------------------
#
# A step used to reach the store only when it *completed*, so the trace carried no
# "started" signal and the canvas had to guess which stage was in flight: it marked the
# next pending card and hoped. A student watching a document index therefore saw a jump
# from nothing to everything rather than parse, then chunk, then embed.


async def test_a_stage_is_recorded_when_it_starts_and_again_when_it_ends(
    store: InMemoryStepStore,
) -> None:
    """Two writes, one row, and the status is the difference between them.

    The intermediate state is asserted from *inside* the region, because that is the
    only moment it exists — checking afterwards would find the finished step and prove
    nothing about what a poll mid-run would have seen.
    """
    with trace_context(session_id="s1", trace_id="t1"):
        async with atrace_step(StepType.CHUNK, label="chunk") as handle:
            mid_run = await store.list_steps(session_id="s1")
            assert [s.status for s in mid_run] == [StepStatus.RUNNING]
            assert mid_run[0].step_type is StepType.CHUNK
            handle.set_output("3 chunks")

    finished = await store.list_steps(session_id="s1")
    assert [s.status for s in finished] == [StepStatus.OK]
    assert finished[0].id == mid_run[0].id, "the finished step must replace the open one"
    assert finished[0].raw_output == "3 chunks"


async def test_a_running_step_carries_no_duration_yet(
    store: InMemoryStepStore,
) -> None:
    """`duration_ms` is zero until the body returns, and the UI must not print it.

    Asserted here rather than left to the template, because "0 ms" beside a stage that
    is still working is a wrong number rather than a missing one — and this platform's
    entire claim is that the numbers on screen are real.
    """
    with trace_context(session_id="s1", trace_id="t1"):
        async with atrace_step(StepType.EMBED, label="embed"):
            open_step = (await store.list_steps(session_id="s1"))[0]
            assert open_step.duration_ms == 0
            assert open_step.usage.cost_usd == Decimal("0")


async def test_a_step_that_fails_leaves_one_row_not_two(
    store: InMemoryStepStore,
) -> None:
    """The error write replaces the running one, exactly as the success write does.

    Worth its own test: the failure path is a separate branch in every one of the three
    emit sites, and a missed replacement there would leave a phantom `running` step in
    the trace for ever — the only kind that never resolves.
    """
    with (  # noqa: PT012 - the traced region is the subject, not a single call
        pytest.raises(ProviderError),
        trace_context(session_id="s1", trace_id="t1"),
    ):
        async with atrace_step(StepType.RETRIEVE, label="retrieve"):
            raise ProviderError("no")

    steps = await store.list_steps(session_id="s1")
    assert [s.status for s in steps] == [StepStatus.ERROR]


async def test_pacing_holds_before_a_watched_stage_and_leaves_the_measurement_alone(
    store: InMemoryStepStore,
) -> None:
    """Slow motion adds gaps, never time to a measurement.

    The pause sits between the `running` write and the body, so a card lights up, holds,
    and then fills with its real data. `duration_ms` is timed across the body alone, so
    a paced run reports exactly what an unpaced one would — which is the property that
    makes a deliberate delay honest in a tool whose whole claim is that the numbers on
    screen are real. If this ever stops being true the pause has moved inside the timer.
    """
    pace_ms = 120
    started = time.perf_counter()
    with trace_context(session_id="s1", trace_id="t1", pace_ms=pace_ms):
        async with atrace_step(StepType.PARSE, label="parse"):
            pass
    elapsed_ms = (time.perf_counter() - started) * 1000

    step = (await store.list_steps(session_id="s1"))[0]
    assert elapsed_ms >= pace_ms, "the pause did not happen"
    assert step.duration_ms < pace_ms, (
        "the pause was timed as part of the step — it must sit before the body, not "
        "inside the measurement"
    )


async def test_pacing_applies_once_per_watched_stage_and_not_to_nested_calls(
    store: InMemoryStepStore,
) -> None:
    """One pause per card, and none for anything the canvas does not draw.

    `@traced` wraps a single external call and `atrace_step` marks a phase of RAG
    somebody named by hand, so gating on the second gives exactly one pause per card.
    Pausing on the first would multiply the delay by the nesting depth — a retrieval
    would hold, then its embedding call would hold again inside it — and would pace
    `ingest`, `iterate`, `call_tool` and `summarize`, none of which is on the canvas.
    """
    pace_ms = 120

    @traced(StepType.EMBED, label="provider.embed")
    async def embed() -> str:
        return "vector"

    started = time.perf_counter()
    with trace_context(session_id="s1", trace_id="t1", pace_ms=pace_ms):
        # `ingest` is not a card, so it is not paced; the retrieval inside it is.
        async with atrace_step(StepType.INGEST, label="ingest"):
            async with atrace_step(StepType.RETRIEVE, label="retrieve"):
                await embed()
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert pace_ms <= elapsed_ms < pace_ms * 2, (
        f"expected exactly one pause, got {elapsed_ms:.0f}ms of a possible "
        f"{pace_ms * 3}ms"
    )
