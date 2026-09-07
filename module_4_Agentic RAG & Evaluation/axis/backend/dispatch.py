"""The Backend → AI Backend seam. The only module in `backend/` that may import
`ai_backend` behaviour.

CLAUDE.md states the Backend "contains no retrieval or generation logic". That is
easy to say and easy to erode: one convenient import of a chunker into a route,
six months later, and the layer boundary is decoration. Funnelling the dependency
through this one module turns the rule into something checkable, and
`tests/unit/test_layer_boundaries.py` fails the build if any other module under
`backend/` imports an AI Backend component.

(Contract *types* — `Strategy`, `AgentStep` — are exempt and imported freely.
They are a shared vocabulary, not logic; the whole point of a shared contract is
that both sides may name the same things.)

Communication is an in-process Python call, not a network hop (System Design
Section 6.2). The separation is real at the code level even without a wire
between the two, and that trade-off is worth stating to students: a distributed
deployment would replace the body of these functions with an internal service
call and change nothing about their signatures.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from decimal import Decimal
from typing import NamedTuple

from ai_backend.agents.rewriter import MAX_HISTORY_TURNS
from ai_backend.config.settings import Settings
from ai_backend.contracts.models import (
    AgentStep,
    Answer,
    IngestionResult,
    Strategy,
    new_id,
)
from ai_backend.contracts.pipeline import (
    CORPORA,
    DEFAULT_CORPUS,
    DEMO_CORPUS,
    QueryBudget,
    QueryContext,
    Turn,
    index_scope,
)
from ai_backend.evaluation.demo import demo_questions, pain_point_demos
from ai_backend.evaluation.golden import demo_documents
from ai_backend.observability import trace_context
from ai_backend.observability.store import AgentStepStore
from ai_backend.pipelines import available as available_strategies
from ai_backend.pipelines import get_pipeline
from ai_backend.runtime import AiRuntime, build_runtime
from ai_backend.summarize import Summary

__all__ = [
    "AiRuntime",
    # Re-exported so the Backend can bound how much conversation it reads
    # without importing the AI Backend directly — `test_layer_boundaries`
    # allows exactly one door and this is it. The *value* belongs to the
    # rewriter, which is the only thing that reads a history.
    #
    # The corpus names travel the same way and for the same reason: the Backend has
    # to validate a browser-supplied corpus and enumerate the scopes a session holds,
    # and neither is a reason to let it import the AI Backend at large.
    "CORPORA",
    "DEFAULT_CORPUS",
    "DEMO_CORPUS",
    "MAX_HISTORY_TURNS",
    "index_scope",
    "DemoDocument",
    "build_runtime",
    "demo_document_set",
    "demo_question_set",
    "pain_point_set",
    "ingest_document",
    "narrate_step",
    "run_query",
    "strategies_available",
    "summarize",
    "total_cost",
    "trace_steps",
]


class DemoDocument(NamedTuple):
    """One demo fixture, ready to hand to the existing upload path."""

    filename: str
    data: bytes


def demo_question_set() -> list[dict[str, str]]:
    """The labelled demo questions, as plain dicts for a JSON response.

    Routed through here because the Frontend may not import `ai_backend` at all
    (layer rule 1) and no other Backend module may import evaluation behaviour
    (rule 2). The labels therefore reach the browser the same way everything else
    does — over HTTP, from an endpoint.

    Serialised to dicts rather than passing the `DemoQuestion` models up, so the
    Backend's response schema owns the wire shape and the evaluation module stays
    free to change its own.
    """
    return [
        {
            "id": q.id,
            "question": q.question,
            "outcome": q.outcome.value,
            "because": q.because,
        }
        for q in demo_questions()
    ]


def pain_point_set(*, settings: Settings | None = None) -> list[dict[str, object]]:
    """The four pain-point demonstrations, as plain dicts for a JSON response.

    Routed through here for the same reason `demo_question_set` is: the Frontend may
    not import `ai_backend`, and no other Backend module may import evaluation
    behaviour. Serialised to dicts so the Backend's response schema owns the wire
    shape and the evaluation module stays free to change its own.

    `settings` decides whether a card may claim a measurement: the recorded verdict is
    only a claim about the embedding model, `top_k`, `min_similarity` and corpus it was
    measured under. Optional so a caller with no settings to hand still works, falling
    back to the process-wide ones.
    """
    return [
        {
            "id": p.id,
            "title": p.title,
            "symptom": p.symptom,
            "mechanism": p.mechanism,
            "measured": p.measured,
            # Empty `measured` and `verified_by_harness=False` travel together: the card
            # has to be able to say *why* it has no figure, not merely lack one.
            "verified_by_harness": p.verified_by_harness,
            "unverified_reason": p.unverified_reason,
            "question": p.question,
            "context_question": p.context_question,
            "golden_id": p.golden_id,
        }
        for p in pain_point_demos(settings=settings)
    ]


def demo_document_set() -> list[DemoDocument]:
    """The fixture documents the labelled questions are labelled *against*.

    The pairing is the whole point. A predicted outcome is a claim about a specific
    corpus, so offering the questions without the documents they were measured on
    would be offering predictions about nothing — which is why PRD Section 6
    requires the questions not be presented as runnable until something is indexed.

    **`demo_documents()`, not `load_documents()`.** The harness corpus is larger —
    it keeps a generated spreadsheet and a chart so the tabular and visual questions
    stay measurable — and a session may hold only `max_files_per_session` files. The
    two were one function until the corpus moved to ACME, at which point the coupling
    became a real constraint: a document added for measurement had to fit inside a
    limit that exists for uploads. This offers the five ACME documents alone, which
    is what the class has seen and exactly the file limit.
    """
    return [
        DemoDocument(filename=document.filename, data=document.data)
        for document in demo_documents()
    ]


async def ingest_document(
    runtime: AiRuntime,
    *,
    session_id: str,
    document_id: str,
    filename: str,
    data: bytes,
    corpus: str = DEFAULT_CORPUS,
    pace_ms: int = 0,
) -> IngestionResult:
    """Index one uploaded document into one corpus.

    A trace context is opened here rather than inside the ingestion pipeline, for
    the same reason `run_query` does it: every path into the AI Backend is
    instrumented identically whether or not its author remembered to be. Ingestion
    gets its own `trace_id` because it is not part of any query — a student should
    be able to see what indexing cost before asking anything.

    **Note which of the two identifiers goes where.** The trace is keyed on the
    *session*, because indexing is something this session did and the Trace page
    lists it beside every other run. The index is keyed on the *scope*, because a
    document belongs to one corpus. Passing the scope to the trace would split a
    session's history in two; passing the session to the index would put a student's
    uploads in with the demo set.
    """
    with trace_context(session_id=session_id, trace_id=new_id(), pace_ms=pace_ms):
        return await runtime.ingest(
            scope=index_scope(session_id, corpus),
            document_id=document_id,
            filename=filename,
            data=data,
            # Recorded on the `ingest` step. The canvas binds its indexing track from
            # those steps, and a track describing a document the active corpus cannot
            # search is a track describing something that will not be found.
            corpus=corpus if corpus in CORPORA else DEFAULT_CORPUS,
        )


def strategies_available() -> tuple[Strategy, ...]:
    """Which strategies can actually run right now.

    A pass-through, so routes and the health check do not import the pipeline
    registry directly.
    """
    return available_strategies()


async def run_query(
    *,
    session_id: str,
    question: str,
    strategy: Strategy,
    budget: QueryBudget,
    pace_ms: int = 0,
    web_enabled: bool = False,
    history: Sequence[tuple[str, str]] = (),
    cache_enabled: bool = True,
    corpus: str = DEFAULT_CORPUS,
) -> Answer:
    """Run one question through one strategy.

    Opens the trace context here rather than inside each pipeline, so that every
    strategy is instrumented identically whether or not its author remembered to
    — which is what makes the four comparable at all. A pipeline that forgot to
    open a trace would silently report zero cost and win every comparison.

    `history` arrives as plain `(question, answer)` pairs rather than as `Turn`
    objects, so the Backend never constructs an AI Backend model — it reads rows out
    of `query_run` and hands them over. The conversion happens here, at the seam.
    """
    ctx = QueryContext(
        session_id=session_id,
        strategy=strategy,
        question=question,
        budget=budget,
        # Only Agentic RAG reads this. Naive RAG has no router to make the choice with,
        # and a baseline reaching a source its comparator cannot is not a baseline.
        web_enabled=web_enabled,
        # Likewise. Both are handed to *both* strategies and ignored by the baseline,
        # so "the baseline has no memory" is a property of the pipeline — visible as
        # the absence of a `rewrite` step — rather than a Backend `if` nobody can see.
        history=tuple(Turn(question=q, answer=a) for q, a in history),
        cache_enabled=cache_enabled,
        # Which corpus this question searches. The pipeline composes it with the
        # session into `ctx.index_scope`; nothing else about the run changes.
        corpus=corpus,
    )
    pipeline = get_pipeline(strategy)

    started = time.perf_counter()
    with trace_context(
        session_id=session_id, trace_id=ctx.trace_id, strategy=strategy, pace_ms=pace_ms
    ):
        answer = await pipeline.run(ctx)

    # Measured out here so a pipeline cannot under-report its own latency.
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return answer.model_copy(update={"latency_ms": elapsed_ms})


async def summarize(
    runtime: AiRuntime,
    *,
    session_id: str,
    budget: QueryBudget,
    filenames: dict[str, str],
    corpus: str = DEFAULT_CORPUS,
    document_ids: Sequence[str] | None = None,
) -> Summary:
    """Summarise a session's indexed documents, or the subset the student chose.

    A trace context is opened here, like `run_query` and `ingest_document`, so that
    every path into the AI Backend is instrumented identically whether or not its
    author remembered to be — and so a student can see what a summary cost next to
    what a query cost, which is the contrast Summarizer mode exists to draw.

    Its own `trace_id`: a summary is not part of any query, and folding it into one
    would put its cost on a question nobody asked.
    """
    with trace_context(session_id=session_id, trace_id=new_id()):
        return await runtime.summarize(
            scope=index_scope(session_id, corpus),
            budget=budget,
            filenames=filenames,
            document_ids=document_ids,
        )


async def trace_steps(
    store: AgentStepStore, *, session_id: str, trace_id: str | None = None
) -> list[object]:
    """Read recorded steps back out of the observability store."""
    return list(await store.list_steps(session_id=session_id, trace_id=trace_id))


async def narrate_step(
    runtime: AiRuntime, store: AgentStepStore, *, step: AgentStep
) -> str:
    """Explain one trace step in plain language, and cache the result.

    Routed through this module rather than called from `backend/api/v1/trace.py`
    because that route may not import `ai_backend.providers` — the un-exemptable
    layer rule, checked by `tests/unit/test_layer_boundaries.py`. The route holds no
    LLM provider; it asks for a narration and gets a string.

    **The stored value is re-read rather than returned directly.**
    `store.set_narration` redacts, so returning the generated text would hand the
    caller an unscrubbed version of exactly the field that redaction exists to
    protect. The extra read is the difference between redaction being enforced and
    being merely applied.
    """
    with trace_context(
        session_id=step.session_id, trace_id=step.trace_id, strategy=step.strategy
    ):
        narration = await runtime.narrate(step)

    await store.set_narration(step.id, narration)
    stored = await store.get_step(step.id)
    return (stored.narration if stored else None) or narration


def total_cost(answer: Answer) -> Decimal:
    """The cost to charge against a session's budget."""
    return answer.usage.cost_usd
