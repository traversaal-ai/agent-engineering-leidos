"""The agent components, tested at the seams the acceptance tests cannot reach.

The eight acceptance criteria prove an agentic query works end to end. They cannot
prove *why* it works, and three of the behaviours here only appear under conditions
an HTTP test cannot arrange: a model returning unparseable output, a budget running
out mid-loop, a model asking for a tool that does not exist.

Each of these is a Section 11 requirement rather than an implementation detail — the
failure modes are specified to be *visible*, and a test that only checks the happy
path would let all of them regress into silence.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from ai_backend.agents.decomposer import Decomposer
from ai_backend.agents.react import ReActLoop
from ai_backend.agents.router import MIN_CONFIDENCE, Router
from ai_backend.agents.spend import QuerySpend
from ai_backend.agents.tools import DocumentSearchTool
from ai_backend.config.settings import Settings
from ai_backend.contracts.models import (
    Chunk,
    RetrievedContext,
    StepStatus,
    StepType,
    Strategy,
    ToolCall,
    Usage,
)
from ai_backend.contracts.pipeline import QueryBudget
from ai_backend.errors import (
    BudgetExceededError,
    ProviderError,
    UnsupportedStrategyError,
)
from ai_backend.observability import InMemoryStepStore, trace_context
from ai_backend.observability import trace as trace_module
from ai_backend.pipelines import available, get_pipeline
from ai_backend.providers.fake import FakeLLMProvider
from ai_backend.runtime import build_runtime

LEAVE = "Parental leave is 16 weeks of fully paid leave after a birth or adoption."


def _budget(
    *,
    cost: float = 1.0,
    llm_calls: int = 10,
    iterations: int = 3,
    tool_calls: int = 5,
) -> QueryBudget:
    return QueryBudget(
        max_cost_usd=cost,
        max_llm_calls=llm_calls,
        max_agent_iterations=iterations,
        max_tool_calls=tool_calls,
    )


@pytest.fixture
def steps():
    """An in-memory step store wired in as the process-wide sink."""
    store = InMemoryStepStore()
    previous = trace_module.get_store()
    trace_module.configure(store=store)
    try:
        yield store
    finally:
        trace_module.configure(store=previous)


class _StubRetriever:
    """Returns chunks only for queries containing a keyword.

    A stub rather than the real `VectorRetriever` because these tests are about the
    loop's control flow, and the interesting cases are "found nothing" and "found
    something on the second phrasing" — which need to be arranged exactly, not
    coaxed out of an embedding model.
    """

    name = "stub"

    def __init__(self, *, answers_to: str) -> None:
        self._answers_to = answers_to
        self.queries: list[str] = []

    async def retrieve(self, query: str, *, session_id: str, top_k: int = 5):
        self.queries.append(query)
        if self._answers_to.lower() in query.lower():
            return RetrievedContext(
                chunks=[
                    Chunk(
                        document_id="d1",
                        content=LEAVE,
                        source_location="p. 1",
                        score=0.9,
                    )
                ],
                usage=Usage(prompt_tokens=3, cost_usd=Decimal("0.0000003")),
            )
        return RetrievedContext(usage=Usage(prompt_tokens=3))

    async def is_ready(self, session_id: str) -> bool:
        return True


# ---------------------------------------------------------------------------
# QuerySpend — the running total
# ---------------------------------------------------------------------------


async def test_spend_accumulates_across_calls_rather_than_resetting() -> None:
    """The defect this class exists to fix.

    The original per-call check compared each estimate against the *whole*
    remaining allowance and decremented nothing, so N calls each individually
    affordable all passed while collectively exceeding the cap. With one call per
    query that is invisible; the agent loop makes it real.
    """
    llm = FakeLLMProvider()
    # Two calls' worth of budget, deliberately. Sized from the fake's own pricing
    # so the third call is the one that must be refused.
    one_call = llm.estimate_cost(prompt_tokens=100, max_completion_tokens=100)
    spend = QuerySpend(_budget(cost=float(one_call * 2 + Decimal("0.0000001"))), llm=llm)

    for _ in range(2):
        spend.reserve(prompt_tokens=100, max_completion_tokens=100)
        spend.record(Usage(prompt_tokens=100, cost_usd=one_call))

    with pytest.raises(BudgetExceededError):
        spend.reserve(prompt_tokens=100, max_completion_tokens=100)


async def test_spend_refuses_the_call_that_exceeds_the_call_count() -> None:
    llm = FakeLLMProvider()
    spend = QuerySpend(_budget(llm_calls=2), llm=llm)

    spend.reserve(prompt_tokens=10, max_completion_tokens=10)
    spend.reserve(prompt_tokens=10, max_completion_tokens=10)

    with pytest.raises(BudgetExceededError) as caught:
        spend.reserve(prompt_tokens=10, max_completion_tokens=10)

    # The message must name the bound that was hit, since the fix differs.
    assert "LLM calls" in caught.value.message
    assert spend.llm_calls == 2, "a refused call must not be counted"


async def test_a_refused_call_is_refused_before_the_provider_is_touched(steps) -> None:
    """CLAUDE.md: caps are "checked *before* the call is made, not after"."""
    llm = FakeLLMProvider()
    spend = QuerySpend(_budget(cost=0.0000001), llm=llm)
    router = Router(llm=llm)

    with trace_context(session_id="s1", trace_id="t1"), pytest.raises(BudgetExceededError):
        await router.route("Anything at all?", spend=spend)

    assert llm.call_count == 0, "the provider was called despite the cap being hit"


async def test_recording_a_call_releases_its_reservation() -> None:
    """Otherwise the pessimistic estimate is charged twice.

    `reserve` prices the completion at its maximum length. If that reservation were
    not replaced by the actual cost, a loop of cheap calls would exhaust the budget
    at a fraction of real spend — a cap that fires far too early is as broken as one
    that fires too late, just less dangerously.
    """
    llm = FakeLLMProvider()
    spend = QuerySpend(_budget(cost=1.0), llm=llm)

    spend.reserve(prompt_tokens=100, max_completion_tokens=700)
    reserved = spend.spent
    spend.record(Usage(prompt_tokens=100, completion_tokens=4, cost_usd=Decimal("0.00001")))

    assert spend.spent == Decimal("0.00001")
    assert spend.spent < reserved
    # The tokens are kept too — this total is what the `Answer` reports, so it has
    # to carry the evidence for the cost, not just the figure.
    assert spend.usage.total_tokens == 104


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


async def test_an_unparseable_classification_falls_back_and_says_so(steps) -> None:
    """Section 11: "Router step shows low-confidence classification + fallback path".

    The fake provider's default response is prose, not a classification, which makes
    this the path every offline test exercises — so it had better be recorded rather
    than merely survived.
    """
    llm = FakeLLMProvider(responses=["I think probably both, hard to say."])
    router = Router(llm=llm)

    with trace_context(session_id="s1", trace_id="t1"):
        decision = await router.route(
            "What is the leave policy?", spend=QuerySpend(_budget(), llm=llm)
        )

    assert decision.fallback_taken is True
    assert decision.needs_decomposition is False, "the cheap branch is the safe guess"

    route_step = next(s for s in steps.all_steps if s.step_type is StepType.ROUTE)
    assert route_step.attributes["fallback_taken"] is True
    assert "confidence" in route_step.attributes


async def test_a_confident_complex_classification_is_acted_on(steps) -> None:
    llm = FakeLLMProvider(responses=["COMPLEXITY: COMPLEX\nCONFIDENCE: 0.9"])
    router = Router(llm=llm)

    with trace_context(session_id="s1", trace_id="t1"):
        decision = await router.route("Compare A with B.", spend=QuerySpend(_budget(), llm=llm))

    assert decision.needs_decomposition is True
    assert decision.fallback_taken is False
    assert decision.confidence == pytest.approx(0.9)


async def test_a_hedged_classification_is_not_acted_on(steps) -> None:
    """A model reporting 0.2 confidence is telling us it cannot tell.

    Acting on it would spend an extra LLM call on a coin flip. The classification is
    ignored but the number is still recorded, so the trace shows the router was
    unsure rather than silently showing the fallback as a decision.
    """
    below = MIN_CONFIDENCE - 0.2
    llm = FakeLLMProvider(responses=[f"COMPLEXITY: COMPLEX\nCONFIDENCE: {below}"])
    router = Router(llm=llm)

    with trace_context(session_id="s1", trace_id="t1"):
        decision = await router.route("Compare A with B.", spend=QuerySpend(_budget(), llm=llm))

    assert decision.needs_decomposition is False
    assert decision.fallback_taken is True
    assert decision.confidence == pytest.approx(below)


# ---------------------------------------------------------------------------
# Decomposer
# ---------------------------------------------------------------------------


async def test_decompose_emits_a_step_even_when_it_does_nothing(steps) -> None:
    """Two acceptance criteria assert `decompose` appears in an agentic trace.

    Beyond satisfying them: an absent step is ambiguous. A student cannot tell "the
    router said this was simple" from "decomposition crashed" from "this build does
    not decompose". A step recording `sub_questions: 1` says which.
    """
    llm = FakeLLMProvider()
    decomposer = Decomposer(llm=llm)

    with trace_context(session_id="s1", trace_id="t1"):
        parts = await decomposer.decompose(
            "What is the leave policy?",
            spend=QuerySpend(_budget(), llm=llm),
            needed=False,
            reason="single lookup",
        )

    assert parts == ["What is the leave policy?"]
    assert llm.call_count == 0, "a skipped decomposition must not cost a call"

    step = next(s for s in steps.all_steps if s.step_type is StepType.DECOMPOSE)
    assert step.attributes["llm_called"] is False
    assert step.attributes["sub_questions"] == 1
    assert step.attributes["sub_questions_text"] == ["What is the leave policy?"]
    assert step.attributes["reason"] == "single lookup"


async def test_decomposition_splits_on_lines_and_strips_list_markers(steps) -> None:
    llm = FakeLLMProvider(
        responses=["1. How long is parental leave?\n2. How many remote days are allowed?"]
    )
    decomposer = Decomposer(llm=llm)

    with trace_context(session_id="s1", trace_id="t1"):
        parts = await decomposer.decompose(
            "Compare leave with remote work.",
            spend=QuerySpend(_budget(), llm=llm),
            needed=True,
            reason="multi-part question",
        )

    assert parts == [
        "How long is parental leave?",
        "How many remote days are allowed?",
    ]

    # The canvas is built on this. Recording only a count — which is what the step
    # carried until Milestone 2b — left the most interesting artefact of an agentic
    # run available nowhere but the model's unparsed `raw_output`, which is why the
    # decomposition was invisible in the UI.
    step = next(s for s in steps.all_steps if s.step_type is StepType.DECOMPOSE)
    assert step.attributes["sub_questions_text"] == parts, (
        "the recorded text must be the *parsed* list the pipeline acted on, not the "
        "model's raw completion"
    )


async def test_too_many_sub_questions_are_dropped_visibly(steps) -> None:
    """A truncated decomposition is a fact about why the answer is incomplete.

    Each sub-question costs a retrieval and competes for space in the synthesis
    prompt, so the cap is necessary — but silently dropping half a question is the
    kind of thing that makes an answer look simply wrong.
    """
    llm = FakeLLMProvider(responses=["\n".join(f"question {i}?" for i in range(9))])
    decomposer = Decomposer(llm=llm)

    with trace_context(session_id="s1", trace_id="t1"):
        parts = await decomposer.decompose(
            "A nine-part question.",
            spend=QuerySpend(_budget(), llm=llm),
            needed=True,
            reason="multi-part question",
        )

    assert len(parts) == 4
    step = next(s for s in steps.all_steps if s.step_type is StepType.DECOMPOSE)
    assert step.attributes["truncated_to"] == 4


# ---------------------------------------------------------------------------
# ReAct loop
# ---------------------------------------------------------------------------


async def test_the_loop_executes_a_tool_call_and_nests_it(steps) -> None:
    """Real tool calling: the model asks, the loop executes, the result comes back.

    Also the nesting assertion. `CALL_TOOL` must be a child of the `ITERATE` step
    that chose it — flat, an agentic trace is a longer list; nested, a student can
    see which decision caused which cost.
    """
    retriever = _StubRetriever(answers_to="parental")
    llm = FakeLLMProvider(
        responses=["Let me try a different phrasing.", "Found it."],
        # First call asks for a tool; the second scripts nothing, so the loop ends.
        tool_calls=[[ToolCall(name="search_documents", arguments={"query": "parental leave"})]],
    )
    loop = ReActLoop(llm=llm, tool=DocumentSearchTool(retriever=retriever, top_k=5))

    with trace_context(session_id="s1", trace_id="t1"):
        found = await loop.resolve(
            "How much time off after a birth?",
            session_id="s1",
            spend=QuerySpend(_budget(), llm=llm),
            budget=_budget(),
        )

    assert not found.is_empty, "the tool's result was not returned to the caller"
    assert retriever.queries == ["parental leave"], "the model's own query was not used"

    iterate = next(s for s in steps.all_steps if s.step_type is StepType.ITERATE)
    tool_step = next(s for s in steps.all_steps if s.step_type is StepType.CALL_TOOL)
    assert tool_step.parent_step_id == iterate.id
    assert tool_step.attributes["chunks_found"] == 1


async def test_the_loop_stops_when_the_agent_proposes_nothing(steps) -> None:
    """No tool calls means the model has concluded. Iterating anyway just bills."""
    llm = FakeLLMProvider(responses=["The documents do not cover this."])
    loop = ReActLoop(
        llm=llm, tool=DocumentSearchTool(retriever=_StubRetriever(answers_to="zzz"), top_k=5)
    )

    with trace_context(session_id="s1", trace_id="t1"):
        found = await loop.resolve(
            "Anything about submarines?",
            session_id="s1",
            spend=QuerySpend(_budget(), llm=llm),
            budget=_budget(iterations=3),
        )

    assert found.is_empty
    assert llm.call_count == 1, "the loop kept going after the agent stopped"
    iterations = [s for s in steps.all_steps if s.step_type is StepType.ITERATE]
    assert len(iterations) == 1
    assert iterations[0].attributes["stopped_reason"]


async def test_hitting_the_iteration_budget_is_recorded_not_raised(steps) -> None:
    """Section 11: "Trace shows 'stopped: budget reached' with partial synthesis".

    The distinction that matters: `BUDGET_EXCEEDED` is not `ERROR`. "The agent
    stopped because we told it to" and "the agent broke" are different lessons, and
    a student seeing red for the first learns the wrong one.
    """
    retriever = _StubRetriever(answers_to="never-matches")
    # Always asks for another tool call, so only the budget can stop it.
    llm = FakeLLMProvider(
        responses=["Trying again."],
        tool_calls=[
            [ToolCall(name="search_documents", arguments={"query": f"attempt {i}"})]
            for i in range(10)
        ],
    )
    loop = ReActLoop(llm=llm, tool=DocumentSearchTool(retriever=retriever, top_k=5))
    budget = _budget(iterations=2, llm_calls=10, tool_calls=10)

    with trace_context(session_id="s1", trace_id="t1"):
        found = await loop.resolve(
            "Unanswerable.", session_id="s1", spend=QuerySpend(budget, llm=llm), budget=budget
        )

    assert found.is_empty
    iterations = [s for s in steps.all_steps if s.step_type is StepType.ITERATE]
    assert len(iterations) == 2, "the iteration bound was not enforced"
    assert all(s.status is not StepStatus.ERROR for s in steps.all_steps), (
        "a bounded stop must not be recorded as an error"
    )


async def test_the_tool_budget_stops_the_loop_and_is_marked(steps) -> None:
    retriever = _StubRetriever(answers_to="never-matches")
    llm = FakeLLMProvider(
        responses=["Trying."],
        tool_calls=[
            [ToolCall(name="search_documents", arguments={"query": f"q{i}"})] for i in range(10)
        ],
    )
    loop = ReActLoop(llm=llm, tool=DocumentSearchTool(retriever=retriever, top_k=5))
    budget = _budget(iterations=5, llm_calls=10, tool_calls=1)

    with trace_context(session_id="s1", trace_id="t1"):
        await loop.resolve(
            "Unanswerable.", session_id="s1", spend=QuerySpend(budget, llm=llm), budget=budget
        )

    tool_calls = [s for s in steps.all_steps if s.step_type is StepType.CALL_TOOL]
    assert len(tool_calls) == 1, "the tool budget was not enforced"

    stopped = [
        s for s in steps.all_steps if s.status is StepStatus.BUDGET_EXCEEDED
    ]
    assert stopped, "hitting the tool budget was not recorded"
    assert stopped[0].attributes["stopped_reason"]


async def test_the_loop_leaves_an_llm_call_for_synthesis(steps) -> None:
    """Exploring until the query has no calls left would find material and then be
    unable to use it — strictly worse than exploring less, and it would look like a
    budget bug rather than a deliberate stop.
    """
    retriever = _StubRetriever(answers_to="never-matches")
    llm = FakeLLMProvider(
        responses=["Trying."],
        tool_calls=[
            [ToolCall(name="search_documents", arguments={"query": f"q{i}"})] for i in range(10)
        ],
    )
    loop = ReActLoop(llm=llm, tool=DocumentSearchTool(retriever=retriever, top_k=5))
    # Two calls total: the loop may use one, and must hold the other back.
    budget = _budget(iterations=5, llm_calls=2, tool_calls=10)

    with trace_context(session_id="s1", trace_id="t1"):
        await loop.resolve(
            "Unanswerable.", session_id="s1", spend=QuerySpend(budget, llm=llm), budget=budget
        )

    assert llm.call_count == 1, (
        f"the loop spent {llm.call_count} of 2 calls, leaving none for the answer"
    )


async def test_a_hallucinated_tool_is_refused_visibly(steps) -> None:
    """A model can ask for a tool that was never offered.

    Section 11 wants the failed call and the fallback both visible, so this is a
    recorded refusal rather than a silent no-op — otherwise the trace shows a tool
    call that appears to have found nothing, which is a different diagnosis.
    """
    llm = FakeLLMProvider(
        responses=["Searching the web."],
        tool_calls=[[ToolCall(name="web_search", arguments={"query": "leave policy"})]],
    )
    retriever = _StubRetriever(answers_to="parental")
    loop = ReActLoop(llm=llm, tool=DocumentSearchTool(retriever=retriever, top_k=5))

    with trace_context(session_id="s1", trace_id="t1"):
        found = await loop.resolve(
            "Leave policy?",
            session_id="s1",
            spend=QuerySpend(_budget(), llm=llm),
            budget=_budget(iterations=1),
        )

    assert found.is_empty
    assert retriever.queries == [], "an unoffered tool reached the retriever"

    tool_step = next(s for s in steps.all_steps if s.step_type is StepType.CALL_TOOL)
    assert tool_step.attributes["unknown_tool"] is True
    assert "web_search" in (tool_step.raw_output or "")


async def test_a_provider_failure_mid_loop_does_not_lose_the_query(steps) -> None:
    """One flaky call costs the exploration, not the answer.

    The escalation loop is the *optional* part of a query. A sub-question that
    already retrieved successfully is still worth synthesising from, so a failure
    here is absorbed and the query continues — losing the whole answer because an
    optional extra step failed would be the wrong trade.

    Absorbed, not hidden: `@traced` records the failed call as `status=error`
    before re-raising into the loop's handler, so the trace shows what broke.
    Section 11 requires the failure be visible; it does not require it be fatal.
    """
    llm = FakeLLMProvider(fail_after=0)
    loop = ReActLoop(
        llm=llm, tool=DocumentSearchTool(retriever=_StubRetriever(answers_to="x"), top_k=5)
    )

    with trace_context(session_id="s1", trace_id="t1"):
        found = await loop.resolve(
            "Anything?",
            session_id="s1",
            spend=QuerySpend(_budget(), llm=llm),
            budget=_budget(iterations=3),
        )

    assert found.is_empty

    failed = [s for s in steps.all_steps if s.status is StepStatus.ERROR]
    assert failed, "a provider failure must be visible in the trace"

    iterations = [s for s in steps.all_steps if s.step_type is StepType.ITERATE]
    assert len(iterations) == 1, "the loop retried a provider that is failing"
    assert iterations[0].attributes["provider_error"] == ProviderError.code


# ---------------------------------------------------------------------------
# Cost attribution
# ---------------------------------------------------------------------------


async def test_an_agentic_answer_reports_every_call_it_made(steps) -> None:
    """The number the whole platform is built to compare.

    This is a regression test for a defect the entire suite missed. The pipeline
    reported `context.usage + completion.usage` — retrieval plus the final answer —
    so the router's and decomposer's calls were charged to nobody. Both strategies
    reported $0.0023 on the golden set, to the cent, and every acceptance test
    passed: they assert on answers, citations and step types, none of which change.

    Two consequences, both bad. The session cap under-charges, because
    `dispatch.total_cost` reads `Answer.usage`. And Compare mode's central claim —
    that agentic orchestration costs more — becomes unfalsifiable, since the extra
    calls are invisible in exactly the field the table reads.
    """
    from ai_backend.contracts.pipeline import QueryContext
    from ai_backend.pipelines.agentic_rag import AgenticRagPipeline

    llm = FakeLLMProvider(responses=["COMPLEXITY: COMPLEX\nCONFIDENCE: 0.9", "a\nb", "Answer [1]."])
    pipeline = AgenticRagPipeline(
        retriever=_StubRetriever(answers_to=""), llm=llm, top_k=5
    )
    ctx = QueryContext(
        session_id="s1", strategy=Strategy.AGENTIC_RAG, question="a and b?", budget=_budget()
    )

    with trace_context(session_id="s1", trace_id=ctx.trace_id):
        answer = await pipeline.run(ctx)

    # Rewrite, route, decompose, synthesize — four calls, and the answer must own
    # every one of them.
    #
    # This was three until the Rewriter was added in front of routing, and the count
    # is asserted rather than merely bounded because it is the price of orchestration
    # against Naive RAG's single call — the number the Compare table exists to show.
    # A stage that appeared without this test noticing would be a stage whose cost
    # nobody had decided to pay.
    assert llm.call_count == 4, (
        f"expected rewrite, route, decompose and synthesize; got "
        f"{llm.call_count} LLM calls"
    )
    assert llm.rewrite_count == 1, "the rewrite stage did not run"
    charged = [s for s in steps.all_steps if s.usage.cost_usd > 0]
    llm_cost = sum(s.usage.cost_usd for s in charged if s.step_type is StepType.GENERATE)

    assert answer.usage.cost_usd >= llm_cost, (
        f"the answer reports ${answer.usage.cost_usd} but the trace shows "
        f"${llm_cost} of LLM spend — calls are going unbilled"
    )


# ---------------------------------------------------------------------------
# Provider capability
# ---------------------------------------------------------------------------


def test_agentic_strategies_are_unavailable_without_tool_calling() -> None:
    """An agent loop whose tools are discarded is Naive RAG with extra steps.

    `OllamaLLMProvider.complete` accepts `tools=` and ignores it, so an agentic run
    there would route, decompose, retrieve, and answer — producing a plausible trace
    and a plausible answer while the one axis this platform teaches went unmeasured.
    Nothing would look broken, which is what makes it worth a test.

    Unavailable rather than fatal: Ollama plus Naive RAG is a good keyless setup and
    must still boot. The reason has to reach the student, though — "not built until
    Milestone 1" would send them looking in entirely the wrong place.
    """
    settings = Settings(
        llm={"provider": "ollama", "model": "llama3.1"},
        embedding={"provider": "ollama", "model": "nomic-embed-text"},
        storage={"db_path": ":memory:"},
    )
    try:
        build_runtime(settings)

        assert Strategy.NAIVE_RAG in available(), "the single-shot path must still work"
        assert Strategy.AGENTIC_RAG not in available()

        with pytest.raises(UnsupportedStrategyError) as caught:
            get_pipeline(Strategy.AGENTIC_RAG)

        detail = caught.value.detail or ""
        assert "AXIS_LLM__PROVIDER" in detail, "the message must name what to change"
        assert "milestone" not in detail.lower(), (
            "this is a configuration problem, not an unbuilt strategy — saying "
            "'Milestone 1' would send the reader to the wrong fix"
        )
    finally:
        # The registry is process-global, so a runtime built here would otherwise
        # leave agentic_rag missing for every test that ran afterwards.
        build_runtime(_settings_with_tools())


def _settings_with_tools() -> Settings:
    return Settings(
        llm={"provider": "fake", "model": "fake-model"},
        embedding={"provider": "fake", "model": "fake-embedding"},
        storage={"db_path": ":memory:"},
    )
