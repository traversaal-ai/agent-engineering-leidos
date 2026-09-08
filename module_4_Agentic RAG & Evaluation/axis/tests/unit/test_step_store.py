"""The `AgentStep` store: both implementations, one contract.

Parametrized over the in-memory and SQLite stores so they cannot drift. That
matters more than it looks: tests run against the in-memory store and a workshop
runs against SQLite, so any behaviour the two disagree on is a bug that ships.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from ai_backend.contracts.models import (
    AgentStep,
    StepStatus,
    StepType,
    Strategy,
    Usage,
    utc_now,
)
from ai_backend.observability.store import (
    InMemoryStepStore,
    SqliteStepStore,
    aggregate_usage,
)


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path):
    if request.param == "memory":
        return InMemoryStepStore()
    return SqliteStepStore(tmp_path / "steps.sqlite")


def _step(session_id: str = "s1", **kwargs) -> AgentStep:
    return AgentStep(
        session_id=session_id,
        trace_id=kwargs.pop("trace_id", "t1"),
        step_type=kwargs.pop("step_type", StepType.RETRIEVE),
        **kwargs,
    )


async def test_a_step_round_trips_with_every_field_intact(store) -> None:
    step = _step(
        parent_step_id="parent-1",
        status=StepStatus.BUDGET_EXCEEDED,
        strategy=Strategy.AGENTIC_RAG,
        label="ReActLoop.iterate",
        raw_input="sub-question 2",
        raw_output="stopped early",
        duration_ms=1234,
        usage=Usage(prompt_tokens=90, completion_tokens=12, cost_usd=Decimal("0.0042")),
        error=None,
        attributes={"iteration": 3, "stopped_reason": "tool budget"},
    )

    await store.append(step)
    loaded = await store.get_step(step.id)

    assert loaded is not None
    assert loaded.parent_step_id == "parent-1"
    assert loaded.status is StepStatus.BUDGET_EXCEEDED
    assert loaded.strategy is Strategy.AGENTIC_RAG
    assert loaded.label == "ReActLoop.iterate"
    assert loaded.duration_ms == 1234
    assert loaded.attributes["iteration"] == 3


async def test_a_strategy_this_build_does_not_know_does_not_break_the_trace(
    tmp_path: Path,
) -> None:
    """A database can outlive the enum that wrote it, and one row must not 500 a trace.

    `agent_step.strategy` is plain `TEXT` with no CHECK constraint, so a row can name a
    strategy this build has never heard of — one that was removed, or one written by a
    newer build. `Strategy(...)` raises `ValueError` on an unknown value, and because
    `list_steps` maps *every* row, a single such row used to take down the whole trace
    fetch for that session.

    **This was not hypothetical reasoning about the future.** Three documents used to
    forbid narrowing the `Strategy` enum on precisely these grounds — that persisted
    rows would become unloadable — a real hazard defended by a comment rather than by
    code. It is defended here now: the step still loads, still reports its type and
    label, and only its strategy degrades to `None`.

    **SQLite only, deliberately unparametrized.** The in-memory store hands back the
    same `AgentStep` object it was given and never deserializes, so it cannot exhibit
    this at all — parametrizing over both would assert the contract against a store
    with no code path to break. The row is forged with raw SQL because the write side
    is typed and correctly *cannot* produce it.
    """
    store = SqliteStepStore(tmp_path / "stale.sqlite")
    step = _step(strategy=Strategy.NAIVE_RAG, label="retrieve")
    await store.append(step)

    with store._connect() as conn:
        conn.execute(
            "UPDATE agent_step SET strategy = ? WHERE id = ?", ("lightrag", step.id)
        )

    loaded = await store.get_step(step.id)
    assert loaded is not None, "an unknown strategy dropped the step entirely"
    assert loaded.strategy is None, "an unknown strategy must not be invented"
    assert loaded.label == "retrieve", "the rest of the step must survive"

    listed = await store.list_steps(session_id="s1")
    assert len(listed) == 1, "one unreadable strategy took down the whole trace"


async def test_cost_survives_the_round_trip_exactly(store) -> None:
    """SQLite has no decimal type, so cost is stored as TEXT.

    Round-tripping through a float and then summing hundreds of per-call costs is
    exactly how a $2.00 cap becomes a $2.03 cap.
    """
    step = _step(usage=Usage(prompt_tokens=1, cost_usd=Decimal("0.000123456789")))

    await store.append(step)
    loaded = await store.get_step(step.id)

    assert loaded is not None
    assert loaded.usage.cost_usd == Decimal("0.000123456789")


async def test_steps_are_listed_in_recording_order(store) -> None:
    """The trace reads top to bottom as the run happened."""
    labels = [f"step-{i}" for i in range(5)]
    for label in labels:
        await store.append(_step(label=label))

    listed = await store.list_steps(session_id="s1")

    assert [s.label for s in listed] == labels


async def test_a_parent_is_listed_before_its_children(store) -> None:
    """Creation order, even when the clock cannot tell the steps apart.

    This is a regression guard for a real, platform-specific bug. A step is
    *written* when it completes, so a parent is inserted after its own children.
    Ordering used to fall back on `started_at`, and on Windows
    `datetime.now()` resolves to roughly 1–15 ms — coarser than these steps take.
    A retrieval and the embedding call inside it were observed with byte-identical
    timestamps, so the tie broke on insertion order and the trace rendered the
    child above its own parent.

    The identical timestamps here are the whole point of the test: it must pass
    with the clock contributing no information at all.
    """
    frozen = utc_now()
    parent = _step(label="retrieve", started_at=frozen)
    child = _step(label="embed", parent_step_id=parent.id, started_at=frozen)

    # Appended child-first, exactly as completion order would.
    await store.append(child)
    await store.append(parent)

    listed = await store.list_steps(session_id="s1")

    assert [s.label for s in listed] == ["retrieve", "embed"], (
        "a child was listed before its parent — trace ordering has regressed to "
        "wall-clock or insertion order"
    )


async def test_sequence_numbers_are_strictly_increasing(store) -> None:
    """The ordering key itself, independent of any store."""
    steps = [_step(label=f"s{i}") for i in range(5)]

    seqs = [s.seq for s in steps]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs), "sequence numbers must be unique"


async def test_steps_are_scoped_by_session(store) -> None:
    await store.append(_step(session_id="mine"))
    await store.append(_step(session_id="theirs"))

    assert len(await store.list_steps(session_id="mine")) == 1


async def test_steps_can_be_filtered_by_trace(store) -> None:
    """One session runs many queries; a trace is one of them.

    Compare mode makes this essential — both strategies produce traces under
    a single session.
    """
    await store.append(_step(trace_id="run-1"))
    await store.append(_step(trace_id="run-2"))
    await store.append(_step(trace_id="run-2"))

    assert len(await store.list_steps(session_id="s1", trace_id="run-2")) == 2


async def test_narration_can_be_attached_after_the_fact(store) -> None:
    """Narration is generated lazily, long after the step was recorded."""
    step = _step()
    await store.append(step)

    await store.set_narration(step.id, "The retriever looked for three chunks.")
    loaded = await store.get_step(step.id)

    assert loaded is not None
    assert loaded.narration == "The retriever looked for three chunks."


async def test_a_subscriber_receives_steps_as_they_are_recorded(store) -> None:
    """Push, not poll — what makes the 2-second live-trace bound comfortable."""
    queue = store.subscribe("s1")

    step = _step(label="live")
    await store.append(step)

    received = queue.get_nowait()
    assert received.id == step.id
    store.unsubscribe("s1", queue)


async def test_subscribers_only_see_their_own_session(store) -> None:
    queue = store.subscribe("mine")

    await store.append(_step(session_id="theirs"))

    assert queue.empty()
    store.unsubscribe("mine", queue)


async def test_unsubscribing_stops_delivery(store) -> None:
    """Otherwise a student reloading the page leaks a queue per reload."""
    queue = store.subscribe("s1")
    store.unsubscribe("s1", queue)

    await store.append(_step())

    assert queue.empty()


async def test_a_missing_step_is_none_not_an_error(store) -> None:
    assert await store.get_step("nope") is None


async def test_secrets_are_scrubbed_at_the_store_boundary(tmp_path: Path) -> None:
    """Redaction is applied by the store, so no call site can bypass it.

    Checked on both implementations, because a store that forgot to redact would
    be a silent leak in exactly the artefact designed to be shown to students.
    """
    secret = "sk-proj-realisticlookingsecret1234567890"
    for store in (
        InMemoryStepStore(secrets=(secret,)),
        SqliteStepStore(tmp_path / "redacted.sqlite", secrets=(secret,)),
    ):
        step = _step(raw_output=f"authorized with {secret}")
        await store.append(step)

        loaded = await store.get_step(step.id)
        assert loaded is not None
        assert secret not in (loaded.raw_output or "")


async def test_narration_is_scrubbed_on_both_stores(tmp_path: Path) -> None:
    """Narration is a leak path, and one store had forgotten it.

    `SqliteStepStore.set_narration` redacted; `InMemoryStepStore.set_narration` did
    not. The gap survived because the boundary test above only exercises `append` —
    so the two implementations disagreed about whether narration needs scrubbing,
    and the permissive one is the one the entire test suite runs against.

    Narration is LLM output *about* a step's raw fields. The realistic leak is a
    provider error echoing a credential into `raw_output`, which the narrator then
    quotes while explaining what went wrong.
    """
    secret = "sk-proj-narrationleakcanary1234567890"
    for store in (
        InMemoryStepStore(secrets=(secret,)),
        SqliteStepStore(tmp_path / "narrated.sqlite", secrets=(secret,)),
    ):
        step = _step()
        await store.append(step)

        await store.set_narration(step.id, f"The call failed with key {secret}.")

        loaded = await store.get_step(step.id)
        assert loaded is not None
        assert loaded.narration, "the narration was dropped rather than scrubbed"
        assert secret not in loaded.narration


async def test_aggregate_usage_sums_across_steps(store) -> None:
    """The only source of session spend, so it agrees with the visible trace."""
    for _ in range(3):
        await store.append(
            _step(
                usage=Usage(
                    prompt_tokens=10, completion_tokens=5, cost_usd=Decimal("0.001")
                )
            )
        )

    total = aggregate_usage(await store.list_steps(session_id="s1"))

    assert total.prompt_tokens == 30
    assert total.completion_tokens == 15
    assert total.cost_usd == Decimal("0.003")


def test_sqlite_store_creates_its_parent_directory(tmp_path: Path) -> None:
    """`var/` will not exist on a fresh checkout.

    A first run should not fail on a missing directory — PRD Section 6's criterion
    starts from a fresh machine.
    """
    target = tmp_path / "nested" / "deeper" / "steps.sqlite"

    SqliteStepStore(target)

    assert target.parent.is_dir()


async def test_the_store_replaces_a_step_rather_than_duplicating_it(store) -> None:
    """A step is written twice — once running, once finished — under one id.

    Parametrized over both stores deliberately. SQLite gets this for free (`id` is its
    primary key and it inserts with `OR REPLACE`) while the in-memory store had to be
    taught it, and the in-memory one is what the whole suite runs against — so a
    disagreement here is a bug that only ever shows up in a workshop. The two have
    diverged before, over whether `set_narration` redacts.

    Appending instead would leave the running row behind, doubling what the raw trace
    shows, what the evaluation harness counts, and what a `retrievals` figure in the
    comparison table means.
    """
    opened = _step()
    await store.append(opened)
    await store.append(
        opened.model_copy(
            update={
                "status": StepStatus.OK,
                "duration_ms": 42,
                "raw_output": "done",
            }
        )
    )

    steps = await store.list_steps(session_id="s1")
    assert len(steps) == 1, "the running row was left behind beside the finished one"
    assert steps[0].status is StepStatus.OK
    assert steps[0].duration_ms == 42
    assert steps[0].raw_output == "done"


async def test_a_step_still_in_flight_reads_back_as_running(store) -> None:
    """The state a live poll sees. Without it there is nothing to draw mid-run."""
    await store.append(_step(status=StepStatus.RUNNING))

    steps = await store.list_steps(session_id="s1")
    assert [s.status for s in steps] == [StepStatus.RUNNING]
