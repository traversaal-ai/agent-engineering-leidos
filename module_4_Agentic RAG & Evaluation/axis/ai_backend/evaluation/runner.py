"""Running the golden set against a strategy.

Reads retrieval results from the trace store rather than by calling the retriever
a second time, which matters for two reasons. It scores the run that actually
happened — a second call could retrieve differently and the score would describe
a run nobody saw. And it works for *any* strategy without the harness knowing how
that strategy retrieves, which is what lets one harness score both of them on equal
terms (System Design Section 12: "reads stored traces").
"""

from __future__ import annotations

import logging
from enum import StrEnum

from ai_backend.config.settings import Settings
from ai_backend.contracts.models import (
    AgentStep,
    Chunk,
    RetrievedContext,
    StepType,
    Strategy,
    new_id,
)
from ai_backend.contracts.pipeline import (
    DEFAULT_CORPUS,
    QueryBudget,
    QueryContext,
    index_scope,
)
from ai_backend.errors import AxisError
from ai_backend.evaluation.golden import GoldenSet, load_golden_set
from ai_backend.evaluation.scoring import (
    AnswerScore,
    QuestionResult,
    Report,
    RetrievalScore,
    score_answer,
    score_retrieval,
)
from ai_backend.observability import InMemoryStepStore, trace_context
from ai_backend.observability import trace as trace_module
from ai_backend.pipelines import get_pipeline
from ai_backend.pipelines.grounding import dedupe_chunks
from ai_backend.runtime import AiRuntime, build_runtime

logger = logging.getLogger("axis.evaluation")


def _scope(session_id: str) -> str:
    """Where the harness puts its fixtures, and reads them back from.

    The default corpus, because that is what a `QueryContext` with no corpus named
    resolves to — and the harness runs the real pipelines, so anything else would
    index the fixtures where retrieval does not look.
    """
    return index_scope(session_id, DEFAULT_CORPUS)

# Generous, because the harness runs offline against fakes by default. A real
# provider run is bounded by the caps in settings, not here.
EVAL_BUDGET = QueryBudget(
    max_cost_usd=10.0, max_llm_calls=20, max_agent_iterations=5, max_tool_calls=8
)


async def run_golden_set(
    *,
    settings: Settings,
    strategy: Strategy = Strategy.NAIVE_RAG,
    golden: GoldenSet | None = None,
    runtime: AiRuntime | None = None,
) -> Report:
    """Ingest the fixtures, ask every question, and score the results."""
    golden = golden or load_golden_set()

    # A fresh in-memory step store: the report is derived from the trace, so it
    # must not see steps from an earlier run.
    store = InMemoryStepStore()
    previous_store = trace_module.get_store()
    trace_module.configure(store=store)

    try:
        runtime = runtime or build_runtime(settings)
        session_id = f"eval-{new_id()[:8]}"

        document_names = await _ingest_fixtures(runtime, golden, session_id)
        # Needed by the coverage measure, and computed once rather than per
        # question: enumerating the index is cheap but not free, and every
        # question would get the same answer.
        chunk_totals = await _chunks_per_document(
            runtime, session_id, document_names
        )

        results: list[QuestionResult] = []
        for question in golden.questions:
            results.append(
                await _run_one(
                    question=question,
                    strategy=strategy,
                    session_id=session_id,
                    store=store,
                    document_names=document_names,
                    chunk_totals=chunk_totals,
                )
            )

        mode = getattr(runtime.retriever, "mode", "")
        return Report(strategy=strategy.value, mode=mode, results=results)
    finally:
        trace_module.configure(store=previous_store)


class Ceiling(StrEnum):
    """Which mechanism's upper bound to measure.

    **Every one of these is the same experiment**, and noticing that is what turned
    one measurement into four: retrieve over a *hand-authored ground truth* for what
    a mechanism should do, compare against retrieving over the question as asked,
    and the delta is that mechanism's value with the model's ability to perform it
    held out.

    Holding the model out is not a compromise, it is the point. Offline the fake
    providers make an agentic run *identical* to a naive one — a stub cannot
    classify, split, chain or resolve anything — so every claim the platform makes
    about orchestration was unobservable exactly where it is cheapest to observe.
    Reading a list needs no model.

    Each also bounds what a real-provider run can achieve. An agentic run below its
    ceiling has a router, decomposer or rewriter problem; one that reaches it has
    nothing left to win from that mechanism and the next improvement has to come
    from retrieval.
    """

    DECOMPOSITION = "decomposition"
    HOP = "hop"
    RESOLUTION = "resolution"
    COVERAGE = "coverage"

    @property
    def mechanism(self) -> str:
        return {
            Ceiling.DECOMPOSITION: "splitting the question",
            Ceiling.HOP: "chaining a second lookup",
            Ceiling.RESOLUTION: "resolving the follow-up",
            Ceiling.COVERAGE: "reading every chunk",
        }[self]


def _queries_for(question, ceiling: Ceiling) -> list[str]:
    """The ground-truth queries this ceiling retrieves over.

    Falls back to the question as written when it declares no ground truth for this
    ceiling, so the aggregate stays comparable to a naive run question-for-question
    rather than skipping rows and quietly changing the denominator.
    """
    if ceiling is Ceiling.DECOMPOSITION:
        return question.sub_questions or [question.question]
    if ceiling is Ceiling.HOP:
        return question.hops or [question.question]
    if ceiling is Ceiling.RESOLUTION:
        # The resolved form only. Not the context question too: a rewriter produces
        # one standalone query, and unioning both would credit resolution with
        # whatever the previous turn happened to find.
        return [question.resolved] if question.is_follow_up else [question.question]
    return [question.question]


def participates(question, ceiling: Ceiling) -> bool:
    """Whether this question carries ground truth for this ceiling.

    What makes the per-question delta table honest: a question with no ground truth
    retrieves over itself in both runs, so its delta is necessarily zero and
    printing it would pad the table with rows that cannot move.
    """
    if ceiling is Ceiling.DECOMPOSITION:
        return question.is_compound
    if ceiling is Ceiling.HOP:
        return question.is_multi_hop
    if ceiling is Ceiling.RESOLUTION:
        return question.is_follow_up
    return question.expect_full_coverage


async def run_ceiling(
    ceiling: Ceiling,
    *,
    settings: Settings,
    golden: GoldenSet | None = None,
    runtime: AiRuntime | None = None,
) -> Report:
    """Retrieval scored over a mechanism's ground truth, not the whole question.

    No pipeline, no router, no LLM — see `Ceiling`.

    **The coverage ceiling is the odd one out**, and it is worth saying why rather
    than leaving the shape of this function looking inconsistent. The other three
    change the *queries*; coverage changes the *measure*. There is no better set of
    queries for "summarize this corpus" — the mechanism that answers it does not
    retrieve at all, it reads everything — so the ceiling is what a map-reduce over
    the whole corpus would reach, which is every chunk. Retrieval is scored on the
    question as written and the comparison is `chunks_read` against
    `chunks_available`.
    """
    golden = golden or load_golden_set()

    store = InMemoryStepStore()
    previous_store = trace_module.get_store()
    trace_module.configure(store=store)

    try:
        runtime = runtime or build_runtime(settings)
        session_id = f"ceiling-{new_id()[:8]}"
        document_names = await _ingest_fixtures(runtime, golden, session_id)
        top_k = settings.retrieval.top_k
        chunk_totals = await _chunks_per_document(
            runtime, session_id, document_names
        )

        results: list[QuestionResult] = []
        for question in golden.questions:
            gathered: list[Chunk] = []
            with trace_context(session_id=session_id, trace_id=new_id()):
                for query in _queries_for(question, ceiling):
                    found = await runtime.retriever.retrieve(
                        query, session_id=_scope(session_id), top_k=top_k
                    )
                    gathered.extend(found.chunks)

            # The same dedupe the agentic pipeline applies before synthesis, so the
            # ceiling is measured against what a real run would actually hand the
            # model rather than against a list containing the same chunk twice.
            context = RetrievedContext(chunks=dedupe_chunks(gathered))
            score = score_retrieval(
                question,
                context,
                document_names=document_names,
                chunk_totals=chunk_totals,
            )

            if ceiling is Ceiling.COVERAGE and question.expect_full_coverage:
                # The mechanism reads every chunk of every expected document, so
                # that is the ceiling. Compared against what top-k reached, which
                # `score_retrieval` has already counted on the baseline run.
                available = sum(
                    chunk_totals.get(name, 0) for name in question.expect_documents
                )
                score = score.model_copy(
                    update={"chunks_read": available, "chunks_available": available}
                )

            results.append(
                QuestionResult(
                    question=question,
                    retrieval=score,
                    # Left empty and declared so by `retrieval_only` below: nothing
                    # was generated, so scoring an answer would be inventing one.
                    answer=AnswerScore(question_id=question.id),
                )
            )

        mode = getattr(runtime.retriever, "mode", "")
        return Report(
            strategy=f"{ceiling.value} ceiling",
            mode=mode,
            results=results,
            retrieval_only=True,
        )
    finally:
        trace_module.configure(store=previous_store)


async def run_decomposition_ceiling(
    *,
    settings: Settings,
    golden: GoldenSet | None = None,
    runtime: AiRuntime | None = None,
) -> Report:
    """The decomposition ceiling. Kept as a name because callers and docs use it."""
    return await run_ceiling(
        Ceiling.DECOMPOSITION, settings=settings, golden=golden, runtime=runtime
    )


async def _chunks_per_document(
    runtime: AiRuntime, session_id: str, document_names: dict[str, str]
) -> dict[str, int]:
    """How many chunks each fixture became, by golden-set name.

    Read from the index rather than by re-chunking, so the denominator of the
    coverage ceiling is the number of chunks that actually exist to be read — the
    same guarantee `_retrieved_context_from_trace` gives the other measures by
    reading the trace instead of re-querying.

    `all_chunks` is on the `VectorStore` protocol, so every store has it; the
    retriever is asked for its store rather than being given one, because the
    harness has no other reason to know how a `Retriever` retrieves.
    """
    store = getattr(runtime.retriever, "_store", None)
    if store is None:
        return {}
    totals: dict[str, int] = {}
    for chunk in await store.all_chunks(session_id=_scope(session_id)):
        name = document_names.get(chunk.document_id)
        if name:
            totals[name] = totals.get(name, 0) + 1
    return totals


async def _ingest_fixtures(
    runtime: AiRuntime, golden: GoldenSet, session_id: str
) -> dict[str, str]:
    """Index every fixture, returning document_id → golden-set name.

    A fixture that fails to ingest is fatal rather than skipped. Continuing would
    produce a report where questions score badly because their document is
    missing, which reads as a retrieval regression and sends the next person
    looking in entirely the wrong place.
    """
    names: dict[str, str] = {}
    with trace_context(session_id=session_id, trace_id=new_id()):
        for document in golden.documents:
            document_id = new_id()
            try:
                await runtime.ingest(
                    # **The same scope the pipeline will read.** The harness runs
                    # the real `QueryContext`, whose `index_scope` composes the
                    # session with a corpus — so ingesting into the bare session id
                    # puts the fixtures somewhere retrieval never looks, and every
                    # question scores zero recall while nothing looks broken.
                    #
                    # Caught by `test_retrieval_meets_its_floor` on the first run
                    # after corpora were added, which is exactly what that floor is
                    # for: a silent zero is the failure mode a gate exists to make
                    # loud.
                    scope=_scope(session_id),
                    document_id=document_id,
                    filename=document.filename,
                    data=document.data,
                )
            except AxisError as exc:
                raise RuntimeError(
                    f"Golden fixture {document.filename!r} failed to ingest: "
                    f"{exc.message}. The evaluation cannot be trusted with a "
                    f"missing document, so the run was abandoned."
                ) from exc
            names[document_id] = document.name
    return names


async def _run_one(
    *,
    question,
    strategy: Strategy,
    session_id: str,
    store: InMemoryStepStore,
    document_names: dict[str, str],
    chunk_totals: dict[str, int] | None = None,
) -> QuestionResult:
    ctx = QueryContext(
        session_id=session_id,
        strategy=strategy,
        question=question.question,
        budget=EVAL_BUDGET,
    )

    try:
        pipeline = get_pipeline(strategy)
        with trace_context(
            session_id=session_id, trace_id=ctx.trace_id, strategy=strategy
        ):
            answer = await pipeline.run(ctx)
    except AxisError as exc:
        # Recorded, not raised. One failing question should not lose the other
        # fourteen — the same reasoning as Compare mode's partial failures.
        return QuestionResult(
            question=question,
            retrieval=RetrievalScore(question_id=question.id),
            answer=AnswerScore(question_id=question.id),
            error=f"{exc.code}: {exc.message}",
        )

    steps = await store.list_steps(session_id=session_id, trace_id=ctx.trace_id)
    context = _retrieved_context_from_trace(steps)

    return QuestionResult(
        question=question,
        retrieval=score_retrieval(
            question,
            context,
            document_names=document_names,
            chunk_totals=chunk_totals,
        ),
        answer=score_answer(question, answer, document_names=document_names),
    )


def _retrieved_context_from_trace(steps: list[AgentStep]) -> RetrievedContext:
    """Reconstruct what retrieval returned, from the trace.

    Only the fields scoring needs — which document each chunk came from — are
    recovered, so the retrieval steps carry their chunk ids in `attributes`.
    Reading the trace rather than re-querying is what keeps the harness
    strategy-agnostic: an agentic run retrieves several times, and summing those
    steps works without the harness knowing it was an agent.
    """
    chunks: list[Chunk] = []
    for step in steps:
        if step.step_type is not StepType.RETRIEVE:
            continue
        for entry in step.attributes.get("retrieved", []) or []:
            chunks.append(
                Chunk(
                    id=entry.get("chunk_id", ""),
                    document_id=entry.get("document_id", ""),
                    content="",
                    source_location=entry.get("source_location", ""),
                    score=entry.get("score"),
                )
            )
    return RetrievedContext(chunks=chunks)
