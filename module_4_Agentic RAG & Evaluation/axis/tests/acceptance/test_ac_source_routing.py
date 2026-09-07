"""PRD Section 5 — student must-have:

    "I want the agentic strategy to choose between my uploaded documents and a live
    web search so that I can see a real routing decision, and disagree with it,
    rather than a fixed pipeline."

PRD Section 6 acceptance criteria, *Choose between documents and the web*:

    Given the agentic strategy and a configured search provider, when a question is
    submitted, then the router records which source it chose and why, and the trace
    shows the choice alongside the confidence behind it.

    Given no search provider is configured, when the agentic strategy runs, then the
    web source is never offered to the model and no web tool appears in the trace —
    the router cannot select a source that does not exist.

    Given a web search is performed, when the session's search-call allowance is
    already spent, then the call is refused before it is made, and its cost appears
    in the session total rather than as zero.

    Given the agentic strategy routes to the web and the naive strategy cannot, when
    both have run, then the comparison says so explicitly rather than reporting the
    naive run as having simply found less.

And *Citations on every answer*, as amended:

    ... at least one citation linking back to a specific source — an uploaded
    document, or a web result with its URL — and the citation states which of the two
    it is ...

    Given an answer citing web results, when it is shown to the student, then its web
    citations are visually distinguishable from document citations.

Milestone 3.

**The second criterion is the one that would fail silently.** A model offered a tool
that cannot work will call it, confidently, on every iteration — and the trace would
show empty results with nothing saying why. So "the option is absent" is asserted on
the router's prompt and the loop's tool list directly, not only on the outcome.

**The last citation criterion replaces a guarantee that used to be structural.** Before
the web route existed, "a student cannot mistake a web result for their own document"
was true because web results were impossible. It is now true only if the UI says so,
which is why it is asserted against rendered HTML rather than against a data shape.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from ai_backend.agents.router import Router, Source, _parse
from ai_backend.agents.spend import QuerySpend
from ai_backend.agents.tools import SEARCH_WEB, WebSearchTool
from ai_backend.contracts.models import SourceKind, Strategy
from ai_backend.contracts.pipeline import QueryBudget
from ai_backend.errors import BudgetExceededError
from ai_backend.observability import trace_context
from ai_backend.providers.fake import FakeLLMProvider, FakeSearchProvider

pytestmark = [
    pytest.mark.story("choose between my uploaded documents and a live web search"),
    pytest.mark.milestone(3),
]

REPO_ROOT = Path(__file__).resolve().parents[2]


def _budget(**overrides) -> QueryBudget:
    base = {
        "max_cost_usd": 1.0,
        "max_llm_calls": 8,
        "max_agent_iterations": 2,
        "max_tool_calls": 4,
        "max_search_calls": 2,
    }
    base.update(overrides)
    return QueryBudget(**base)


# -- the router records the choice and the reason ---------------------------


async def test_the_router_records_source_reason_and_confidence() -> None:
    """"the router records which source it chose and why".

    All three on the step, because they answer different questions a student asks in
    order: *what* did it decide, *why*, and *how sure was it*. A trace carrying the
    decision without the reason gives them nothing to disagree with, which is the
    entire point of showing the decision at all.
    """
    llm = FakeLLMProvider(
        responses=["SOURCE: WEB\nCOMPLEXITY: SIMPLE\nCONFIDENCE: 0.9\nREASON: asks about this year's releases"]
    )
    router = Router(llm=llm, web_available=True)

    with trace_context(session_id="s1", trace_id="t1"):
        decision = await router.route(
            "What LLMs came out this year?", spend=QuerySpend(_budget(), llm=llm)
        )

    assert decision.source is Source.WEB
    assert decision.confidence == pytest.approx(0.9)
    assert decision.reason == "asks about this year's releases"
    assert not decision.fallback_taken


async def test_the_reason_is_the_models_own_words_not_a_canned_string() -> None:
    """The reason has to be authored by the model to be worth reading.

    It used to be one of two fixed strings chosen from the classification, which made
    it a restatement of the decision rather than a justification of it — "single
    lookup" tells a student nothing they cannot already see in the label next to it.
    """
    llm = FakeLLMProvider(
        responses=[
            "SOURCE: DOCUMENTS\nCOMPLEXITY: SIMPLE\nCONFIDENCE: 0.8\n"
            "REASON: parental leave is internal policy"
        ]
    )
    with trace_context(session_id="s1", trace_id="t1"):
        decision = await Router(llm=llm, web_available=True).route(
            "How long is parental leave?", spend=QuerySpend(_budget(), llm=llm)
        )

    assert "internal policy" in decision.reason
    assert decision.reason not in {"single lookup", "multi-part question"}


def test_an_unreadable_or_unsure_answer_falls_back_to_documents() -> None:
    """Both dimensions fall back together, to the cheap and checkable branch.

    The asymmetry argument, asserted: guessing WEB spends money at a third party for
    material the student cannot check against their own files, and drags the
    prompt-injection surface in with it. Guessing DOCUMENTS is free and fails as an
    empty retrieval, which the pipeline already renders as a visible step.
    """
    for text in (
        "I think maybe the web?",  # no parseable classification
        "SOURCE: WEB\nCOMPLEXITY: COMPLEX\nCONFIDENCE: 0.2\nREASON: not sure",  # too unsure
        "COMPLEXITY: SIMPLE\nCONFIDENCE: 0.9\nREASON: no source line",  # half-read
    ):
        decision = _parse(text, web_available=True)
        assert decision.source is Source.DOCUMENTS, text
        assert decision.needs_decomposition is False, text
        assert decision.fallback_taken is True, text


# -- a source that does not exist is never offered --------------------------


def test_the_web_option_is_absent_from_the_prompt_when_search_is_disabled() -> None:
    """"the web source is never offered to the model".

    Asserted on the prompt rather than on the outcome. A model told it may search the
    web when nothing can will route there confidently and find nothing every time,
    and the trace would show empty results with no explanation — the failure would
    look like broken retrieval rather than a misconfiguration.
    """
    llm = FakeLLMProvider(responses=["COMPLEXITY: SIMPLE\nCONFIDENCE: 0.9"])

    without = Router(llm=llm, web_available=False).system_prompt()
    with_web = Router(llm=llm, web_available=True).system_prompt()

    # And the same question asked per call, which is how the student's toggle reaches
    # the Router: a configured provider the query declined must produce the
    # documents-only prompt, identical to having no provider at all.
    declined = Router(llm=llm, web_available=True).system_prompt(web_available=False)
    assert declined == without

    assert "WEB" not in without, without
    assert "SOURCE" not in without, without
    assert "WEB" in with_web


def test_a_documents_only_router_does_not_report_a_fallback() -> None:
    """An absent SOURCE line is expected when none was asked for.

    Reporting it as unread would set `fallback_taken` on every documents-only run,
    and a flag that is always true tells a student nothing — it would quietly destroy
    the Section 11 signal it exists to carry.
    """
    decision = _parse(
        "COMPLEXITY: COMPLEX\nCONFIDENCE: 0.9\nREASON: two topics",
        web_available=False,
    )

    assert decision.source is Source.DOCUMENTS
    assert decision.needs_decomposition is True
    assert decision.fallback_taken is False


async def test_no_web_tool_reaches_the_model_when_search_is_disabled(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """End to end: the default configuration has no web route at all.

    `settings` in conftest configures the fake search provider, so this asserts the
    *trace* rather than the config: with the fake LLM the router falls back to
    documents and no `search_web` tool step is ever recorded.
    """
    session_id = str(session["session_id"])
    body = (
        await client.post(
            f"/api/v1/sessions/{session_id}/query",
            json={"question": "What is the leave policy?", "strategy": Strategy.AGENTIC_RAG.value},
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

    tools = {(s.get("attributes") or {}).get("tool") for s in steps}
    assert SEARCH_WEB not in tools, tools


# -- the search allowance is enforced before the request --------------------


async def test_the_search_cap_refuses_before_the_request_is_made() -> None:
    """"the call is refused before it is made".

    `call_count` is the assertion: proving a request did *not* happen cannot be done
    from a response body. The cap is per-query and separate from the tool budget,
    because search is billed per request — a token estimate cannot bound it, and a
    three-word query priced per million tokens rounds to nothing.
    """
    provider = FakeSearchProvider()
    tool = WebSearchTool(provider=provider)
    llm = FakeLLMProvider(responses=["anything"])
    spend = QuerySpend(_budget(max_search_calls=1), llm=llm)

    with trace_context(session_id="s1", trace_id="t1"):
        first = await tool.run({"query": "newest llms"}, spend=spend)
        assert first.sources
        assert provider.call_count == 1

        with pytest.raises(BudgetExceededError):
            await tool.run({"query": "newest llms again"}, spend=spend)

    assert provider.call_count == 1, "a search was made after the allowance was spent"


async def test_a_search_costs_money_rather_than_reading_as_free() -> None:
    """"its cost appears in the session total rather than as zero".

    Search is priced per call, which `PRICES` cannot express — a per-MTok rate over a
    few query tokens rounds to nothing, and the web route would have looked free in
    the one table built to compare costs.
    """
    provider = FakeSearchProvider()
    llm = FakeLLMProvider(responses=["anything"])
    spend = QuerySpend(_budget(), llm=llm)

    with trace_context(session_id="s1", trace_id="t1"):
        result = await WebSearchTool(provider=provider).run(
            {"query": "anything"}, spend=spend
        )

    assert result.usage.cost_usd > 0, "a paid search reported no cost"
    assert spend.usage.cost_usd > 0, "the search cost never reached the query total"
    assert spend.search_calls == 1


async def test_an_empty_query_costs_nothing_and_makes_no_request() -> None:
    """A model can emit a tool call with no usable arguments.

    That is a model error, not an Axis error, and it must not be charged for or sent.
    """
    provider = FakeSearchProvider()
    llm = FakeLLMProvider(responses=["anything"])
    spend = QuerySpend(_budget(), llm=llm)

    with trace_context(session_id="s1", trace_id="t1"):
        result = await WebSearchTool(provider=provider).run({"query": "  "}, spend=spend)

    assert result.is_empty
    assert provider.call_count == 0
    assert spend.search_calls == 0


# -- citations state which kind they are ------------------------------------


def test_a_web_citation_carries_its_url_and_no_document_id() -> None:
    """The amended citation criterion, at the data layer.

    `document_id` must stay empty for a web citation. It is a foreign key into the
    Backend's document table and the evaluation harness scores document recall on it,
    so putting a URL there would make a search result look like an uploaded file to
    both.
    """
    from ai_backend.contracts.models import WebSource
    from ai_backend.pipelines.grounding import extract_citations, passages_from

    passages = passages_from(
        [],
        [WebSource(title="A page", url="https://example.test/a", snippet="Some text.")],
    )
    citations = extract_citations("The answer is here [1].", passages)

    assert len(citations) == 1
    citation = citations[0]
    assert citation.kind is SourceKind.WEB
    assert citation.url == "https://example.test/a"
    assert citation.document_id == ""


def test_passage_numbering_and_citation_resolution_cannot_disagree() -> None:
    """Documents and web results share one numbering, built once.

    The two functions used to take `list[Chunk]`; with two kinds of source, any
    divergence between how the prompt numbers passages and how a marker is resolved
    would attribute an answer to the wrong source — the distinguishability failure
    arriving through the back door.
    """
    from ai_backend.contracts.models import Chunk, WebSource
    from ai_backend.pipelines.grounding import (
        extract_citations,
        number_passages,
        passages_from,
    )

    passages = passages_from(
        [Chunk(id="c1", document_id="d1", content="Doc text.", source_location="p. 1")],
        [WebSource(title="Page", url="https://example.test/b", snippet="Web text.")],
    )
    rendered = number_passages(passages)

    # Documents first, web second, and the web one labelled as such — which is what
    # the system prompt's untrusted-snippet rule refers to.
    assert "[1] (p. 1)" in rendered
    assert "[2] WEB RESULT" in rendered

    resolved = extract_citations("Both [1] and [2].", passages)
    assert [c.kind for c in resolved] == [SourceKind.DOCUMENT, SourceKind.WEB]


def test_a_marker_past_the_end_is_still_dropped() -> None:
    """The anti-fabrication guard survives the mixed-source change.

    A model emitting [9] against two passages has invented a source, and rendering it
    would teach a student to trust a citation that was made up.
    """
    from ai_backend.contracts.models import WebSource
    from ai_backend.pipelines.grounding import extract_citations, passages_from

    passages = passages_from([], [WebSource(url="https://example.test/c", snippet="x")])

    assert extract_citations("As shown [9].", passages) == []


class _EmptyRetriever:
    """Finds nothing, always.

    So a `WEB` route has nothing to fall back on and the answer must be built from
    search results or not at all — which is the case worth asserting. A retriever
    that returned material would let a passing test hide a web route that never
    reached the web.
    """

    name = "empty"

    async def retrieve(self, query: str, *, session_id: str, top_k: int = 5):
        from ai_backend.contracts.models import RetrievedContext

        return RetrievedContext()

    async def is_ready(self, session_id: str) -> bool:
        return True


async def test_a_web_routed_answer_is_built_and_cited_from_search_results(step_store) -> None:
    """The whole route, end to end: router chooses WEB, the answer cites a URL.

    Scripted rather than driven through a real model, because the point is the
    *plumbing* — that a WEB decision reaches the loop, that the loop is offered the
    web tool, that snippets reach synthesis, and that the resulting citation is
    marked `web` with its URL intact. A real model's willingness to route is a
    separate question and not one a test should depend on.
    """
    from ai_backend.contracts.models import ToolCall
    from ai_backend.contracts.pipeline import QueryContext
    from ai_backend.pipelines.agentic_rag import AgenticRagPipeline

    llm = FakeLLMProvider(
        responses=[
            # route
            "SOURCE: WEB\nCOMPLEXITY: SIMPLE\nCONFIDENCE: 0.9\nREASON: about this year",
            # the loop's first iteration: call the web tool
            "",
            # synthesis
            "The newest models shipped this year [1].",
        ],
        tool_calls=[
            [],
            [ToolCall(id="tc1", name=SEARCH_WEB, arguments={"query": "newest models"})],
            [],
        ],
    )
    search = FakeSearchProvider(
        results=[
            {
                "title": "Model releases",
                "url": "https://example.test/releases",
                "snippet": "Several models shipped this year.",
            }
        ]
    )
    pipeline = AgenticRagPipeline(
        retriever=_EmptyRetriever(), llm=llm, top_k=5, search=search
    )
    ctx = QueryContext(
        session_id="s1",
        strategy=Strategy.AGENTIC_RAG,
        question="What models came out this year?",
        budget=_budget(),
        # The student's toggle, on. Off is the default — configuring a provider makes
        # the route available and asking for it is a separate act — so a test of the
        # web route has to opt in exactly as the sidebar does.
        web_enabled=True,
    )

    with trace_context(session_id="s1", trace_id=ctx.trace_id):
        answer = await pipeline.run(ctx)

    assert search.call_count == 1, "the WEB route never reached the search provider"
    assert answer.grounded, answer.text
    assert len(answer.citations) == 1
    citation = answer.citations[0]
    assert citation.kind is SourceKind.WEB
    assert citation.url == "https://example.test/releases"
    assert citation.document_id == ""

    # The route is on the trace, and the search cost is in the answer's total.
    route = next(s for s in step_store.all_steps if s.step_type.value == "route")
    assert route.attributes["source"] == "web"
    assert answer.usage.cost_usd >= search.estimate_cost()


async def test_a_documents_route_never_calls_the_search_provider(step_store) -> None:
    """Having a provider configured is not the same as using it.

    The router's decision has to actually gate the spend — otherwise every query
    would pay for a search, and the Compare table's `web searches` row would be
    identical for every question.
    """
    from ai_backend.contracts.pipeline import QueryContext
    from ai_backend.pipelines.agentic_rag import AgenticRagPipeline

    llm = FakeLLMProvider(
        responses=[
            "SOURCE: DOCUMENTS\nCOMPLEXITY: SIMPLE\nCONFIDENCE: 0.9\nREASON: internal policy",
            "",
            "Nothing found.",
        ]
    )
    search = FakeSearchProvider()
    pipeline = AgenticRagPipeline(
        retriever=_EmptyRetriever(), llm=llm, top_k=5, search=search
    )
    ctx = QueryContext(
        session_id="s1",
        strategy=Strategy.AGENTIC_RAG,
        question="How long is parental leave?",
        budget=_budget(),
    )

    with trace_context(session_id="s1", trace_id=ctx.trace_id):
        await pipeline.run(ctx)

    assert search.call_count == 0, "a documents-routed query paid for a web search"


# -- a route that found nothing has to say where it looked ------------------
#
# **These are regressions for a bug that made a correct run unreadable.** A student
# asked for the current weather with the toggle on. The router chose WEB at 0.9
# confidence, the agent wrote its own query, the search ran — and the answer read "I
# could not find anything relevant to that question in the documents you uploaded.
# Nothing here is grounded in your material." One refusal string was used on every
# route, and on a web route it described a run that had not happened. The reasonable
# reading of that sentence is that the web route never fired, which is what was
# reported.


async def test_a_web_route_that_finds_nothing_does_not_blame_the_documents(
    step_store,
) -> None:
    """The refusal has to name what was actually searched.

    Scripted to reproduce the observed failure exactly: a WEB route, a real search
    call, and a model that answers `NO_RELEVANT_CONTENT` because the snippets do not
    contain the answer. That is the ordinary outcome of a question the web cannot
    settle, so it is the wording a class will meet most often.
    """
    from ai_backend.contracts.models import ToolCall
    from ai_backend.contracts.pipeline import QueryContext
    from ai_backend.pipelines.agentic_rag import AgenticRagPipeline

    llm = FakeLLMProvider(
        responses=[
            "SOURCE: WEB\nCOMPLEXITY: SIMPLE\nCONFIDENCE: 0.9\nREASON: current weather",
            "",
            # The synthesis prompt's own sentinel for "the passages do not answer it".
            "NO_RELEVANT_CONTENT",
        ],
        tool_calls=[
            [],
            [ToolCall(id="tc1", name=SEARCH_WEB, arguments={"query": "weather NYC"})],
            [],
        ],
    )
    search = FakeSearchProvider()
    pipeline = AgenticRagPipeline(
        retriever=_EmptyRetriever(), llm=llm, top_k=5, search=search
    )
    ctx = QueryContext(
        session_id="s1",
        strategy=Strategy.AGENTIC_RAG,
        question="What is the current weather in New York?",
        budget=_budget(),
        web_enabled=True,
    )

    with trace_context(session_id="s1", trace_id=ctx.trace_id):
        answer = await pipeline.run(ctx)

    assert search.call_count == 1, "the WEB route never reached the search provider"
    assert not answer.grounded

    text = answer.text.lower()
    assert "documents you uploaded" not in text, (
        "a web-routed run told the student it had searched their documents"
    )
    assert "web" in text, (
        "the refusal does not say the web was searched, so a correct routing "
        "decision still reads as one that never happened"
    )

    # The trace and the answer have to agree. A refusal naming the web beside a route
    # step saying documents would be the same defect wearing the other hat.
    route = next(s for s in step_store.all_steps if s.step_type.value == "route")
    assert route.attributes["source"] == "web"


async def test_a_documents_route_still_says_documents() -> None:
    """The baseline's wording is unchanged, which is what keeps the two comparable.

    Naive RAG has no router and cannot search anywhere else, so its refusal is a fact
    rather than one of three possibilities — and an agentic run that searched only the
    documents must produce the same sentence, or Compare would show two strategies
    disagreeing about a failure they shared.
    """
    from ai_backend.contracts.pipeline import QueryContext
    from ai_backend.pipelines.agentic_rag import AgenticRagPipeline
    from ai_backend.pipelines.grounding import UNGROUNDED_ANSWER

    llm = FakeLLMProvider(
        responses=[
            "SOURCE: DOCUMENTS\nCOMPLEXITY: SIMPLE\nCONFIDENCE: 0.9\nREASON: internal",
            "",
        ]
    )
    search = FakeSearchProvider()
    pipeline = AgenticRagPipeline(
        retriever=_EmptyRetriever(), llm=llm, top_k=5, search=search
    )
    ctx = QueryContext(
        session_id="s1",
        strategy=Strategy.AGENTIC_RAG,
        question="How long is parental leave?",
        budget=_budget(),
        web_enabled=True,
    )

    with trace_context(session_id="s1", trace_id=ctx.trace_id):
        answer = await pipeline.run(ctx)

    assert search.call_count == 0
    assert answer.text == UNGROUNDED_ANSWER


async def test_the_refusal_counts_the_search_that_ran_not_the_route_that_was_chosen(
) -> None:
    """A `SOURCE: WEB` decision is an intention. The refusal reports the act.

    The two legitimately diverge: the agent can satisfy a web-routed question out of
    the documents, or spend its search allowance before a call is made. Claiming a
    paid third-party search Axis never made is the same lie as denying one it did,
    which is why the wording counts `spend.search_calls` rather than reading
    `decision.source`.
    """
    from ai_backend.agents.tools import SEARCH_DOCUMENTS
    from ai_backend.contracts.models import ToolCall
    from ai_backend.contracts.pipeline import QueryContext
    from ai_backend.pipelines.agentic_rag import AgenticRagPipeline

    llm = FakeLLMProvider(
        responses=[
            "SOURCE: WEB\nCOMPLEXITY: SIMPLE\nCONFIDENCE: 0.9\nREASON: sounds current",
            "",
            "",
        ],
        tool_calls=[
            [],
            # Routed to the web; reached for the documents anyway.
            [ToolCall(id="tc1", name=SEARCH_DOCUMENTS, arguments={"query": "leave"})],
            [],
        ],
    )
    search = FakeSearchProvider()
    pipeline = AgenticRagPipeline(
        retriever=_EmptyRetriever(), llm=llm, top_k=5, search=search
    )
    ctx = QueryContext(
        session_id="s1",
        strategy=Strategy.AGENTIC_RAG,
        question="How long is parental leave?",
        budget=_budget(),
        web_enabled=True,
    )

    with trace_context(session_id="s1", trace_id=ctx.trace_id):
        answer = await pipeline.run(ctx)

    assert search.call_count == 0, "no web search was made"
    assert "web" not in answer.text.lower(), (
        "the refusal claimed a web search on a run that never made one"
    )


# -- and the canvas has to show that the search happened --------------------


def _card_art(step: dict, *, web_step: dict | None = None) -> str:
    """Render one card's miniature, the way the canvas does.

    Rendered rather than asserted against the template source, because the defect this
    guards was a *binding* — the markup for a search was always there and the card was
    never given a step to draw.
    """
    from jinja2 import Environment, FileSystemLoader

    env = Environment(
        loader=FileSystemLoader(str(REPO_ROOT / "frontend" / "templates")),
        autoescape=True,
    )
    return env.get_template("_card_art.html").render(step=step, web_step=web_step)


def _tool_step(**overrides) -> dict:
    step = {
        "id": "t1",
        "seq": 9,
        "step_type": "call_tool",
        "parent_step_id": "i1",
        "duration_ms": 120,
        "cost_usd": 0.015,
        "raw_output": "Found 1 web result(s).",
        "attributes": {
            "tool": "search_web",
            "query": "current weather in New York",
            "web_results_found": 1,
            "web_sources": [
                {"title": "Weather today", "url": "https://example.test/nyc/weather"}
            ],
        },
    }
    step.update(overrides)
    return step


def test_the_web_search_is_found_even_though_it_is_not_a_top_level_step() -> None:
    """The lookup the Search card depends on, and why it is not the ordinary one.

    `_bind_stages` binds a stage only when the step has no parent, and a tool call sits
    two levels down — under `iterate`, which is the top-level step. So the web search
    could never bind by the normal rule, and on a `WEB` route there is no `retrieve`
    step to bind either. The card rendered `pending` while Augment and Generate beside
    it showed done, which is the canvas saying the search never ran.
    """
    from frontend.app import _web_search_step

    iterate = {"id": "i1", "seq": 8, "step_type": "iterate", "attributes": {}}
    first = _tool_step(id="t1", seq=9)
    second = _tool_step(id="t2", seq=11)

    found = _web_search_step([iterate, first, second])

    assert found is not None, "the web search was not found under its parent"
    assert found["id"] == "t2", "the card must draw the most recent search"


def test_a_refused_search_is_not_drawn_as_one_that_happened() -> None:
    """A call stopped by the search allowance records the tool and no result count.

    Drawing it as a search would report a paid third-party request that was refused
    before it was made — the same class of claim the refusal wording exists to avoid,
    and the reason this matches on `web_results_found` as well as the tool name.
    """
    from frontend.app import _web_search_step

    refused = _tool_step(attributes={"tool": "search_web", "query": "weather"})

    assert _web_search_step([refused]) is None


def test_the_search_card_draws_the_query_the_model_wrote() -> None:
    """"every stage's real data is visible on the canvas, without a click".

    The agent's own wording is the whole of the routing lesson at card size: it is the
    only text on the canvas the model wrote in order to *act* rather than to answer.
    The host goes with it, because whether to trust a web-grounded answer is a question
    about whose page it came from.
    """
    html = _card_art(_tool_step())

    assert "current weather in New York" in html, "the card does not draw the query"
    assert "example.test" in html, "the card does not say where the answer came from"
    assert "Weather today" in html
    assert 'class="art--plain"' not in html, (
        "the most-searched stage fell through to the generic raw-text miniature"
    )


def test_a_route_that_used_both_sources_draws_neither_of_them_away() -> None:
    """A `BOTH` route retrieves *and* searches, and the card names one stage.

    `retrieve` legitimately binds the document search there, so without this the paid
    half of the run would be drawn nowhere — a student would see a documents-only run
    that had in fact reached the web, which is the same invisibility in a subtler form.
    """
    retrieve = {
        "id": "r1",
        "seq": 7,
        "step_type": "retrieve",
        "duration_ms": 40,
        "cost_usd": 0.0,
        "attributes": {
            "chunks_found": 2,
            "threshold": 0.25,
            "candidates": [{"score": 0.7, "kept": True}, {"score": 0.1, "kept": False}],
        },
    }

    html = _card_art(retrieve, web_step=_tool_step())

    assert 'class="ranks"' in html, "the document ranking stopped being drawn"
    assert "from the web" in html, "the web half of a BOTH route is drawn nowhere"


async def test_the_canvas_does_not_show_the_search_as_never_run(
    client: httpx.AsyncClient, fake_llm: FakeLLMProvider
) -> None:
    """The whole binding, through the app, because the miniature was never the bug.

    A `WEB` route emits no `retrieve` step and the tool call nests under `iterate`, so
    the Search card had nothing bound to it and rendered `pending` — while Augment and
    Generate beside it rendered done. A student who had just watched the router choose
    the web read the canvas as saying it never searched, and reported that.

    Driven through `/ask` rather than by rendering the template, because the two unit
    tests above would all still pass with the one binding line deleted.
    """
    from ai_backend.contracts.models import ToolCall

    # The fixture provider the composed app actually calls. Scripted in place so the
    # run takes the web route and the agent reaches for the tool.
    fake_llm._responses[:] = [  # noqa: SLF001
        "SOURCE: WEB\nCOMPLEXITY: SIMPLE\nCONFIDENCE: 0.9\nREASON: current weather",
        "",
        "The weather is in the snippet [1].",
    ]
    fake_llm._tool_calls[:] = [  # noqa: SLF001
        [],
        [ToolCall(id="tc1", name=SEARCH_WEB, arguments={"query": "weather in Lahore"})],
        [],
    ]

    # Permission, the way the sidebar grants it. Capability is the suite's configured
    # provider; without this the router is never offered `WEB` at all.
    await client.post("/websearch", data={"on": "1"})
    await client.post(
        "/ask",
        data={"question": "What is the weather?", "strategy": Strategy.AGENTIC_RAG.value},
    )
    page = (await client.get("/")).text

    card = re.search(r'data-type="retrieve"[^>]*data-state="(\w+)"', page)
    assert card, "the canvas has no Search card at all"
    assert card.group(1) == "done", (
        f"the Search card is {card.group(1)!r} on a run that searched the web"
    )
    assert "weather in Lahore" in page, (
        "the card is bound but draws nothing the search actually did"
    )


def test_the_synthesis_prompt_can_report_a_near_match_rather_than_refusing() -> None:
    """**A prompt contract, asserted on the prompt, because nothing else can see it.**

    Every LLM in the suite is a scripted double: it returns what a test told it to and
    never reads the system prompt. So the one behaviour this guards — the model answering
    from a snippet that gives the asked-for fact about a neighbouring subject instead of
    replying `NO_RELEVANT_CONTENT` — cannot be exercised offline. What can be pinned is
    the instruction, and that is worth pinning, because it was written for document RAG
    and removing it is a one-line edit that looks tidier.

    The failure it exists to prevent: a search for the current weather in Islamabad
    returned *"Pagh, Islamabad · Current Weather. 6:49 PM. 90°F. Mostly sunny."* and the
    model refused, because the question named the city and only its districts appeared
    beside a temperature. The route, the query and the results were all in the trace; the
    answer said nothing had been found.

    Behavioural verification is `python -m ai_backend.evaluation --compare-strategies`,
    which exits non-zero unless all four deliberately-unanswerable golden questions are
    still refused — that is the check on the *other* direction, that this licence did not
    become a licence to answer anything.
    """
    from ai_backend.pipelines.grounding import NO_CONTENT_SENTINEL, SYSTEM_PROMPT

    # The sentinel is scoped to "nothing about it", not to "not exactly it". That
    # narrowing is the fix; without it the rest of the rule is unreachable.
    assert "says anything about what was asked" in SYSTEM_PROMPT, (
        "the refusal sentinel is not scoped, so a passage that gives the asked-for fact "
        "about a neighbouring subject reads as grounds to refuse"
    )
    assert "not merely when none of them answers it exactly" in SYSTEM_PROMPT

    # And the licence itself, with the condition that makes it safe: the difference has
    # to be named in the answer, or a near match becomes an exact one.
    assert "name that difference in the same sentence" in SYSTEM_PROMPT, (
        "the prompt permits reporting a near match without requiring it to be labelled "
        "as one, which is worse than refusing"
    )
    assert "Never present a near match as an exact one" in SYSTEM_PROMPT

    # The licence must not have quietly become permission to invent. Both halves of the
    # original rule survive, and the sentinel still exists to be returned.
    assert "Do not guess, infer beyond the text" in SYSTEM_PROMPT
    assert "never use outside knowledge" in SYSTEM_PROMPT
    assert NO_CONTENT_SENTINEL in SYSTEM_PROMPT
    assert "Cite every claim" in SYSTEM_PROMPT


def test_a_refusal_does_not_promise_evidence_it_cannot_carry() -> None:
    """A refusal is `grounded=False` with no citations, so it has no sources to show.

    Both web wordings used to end "here is what I searched for and what it returned",
    above nothing at all — on the one run where that was most misleading, the search had
    come back with a temperature and the student could not see it.

    They point at the **trace**, not at the canvas's Search card, even though the card is
    the nicer artefact: an answer is rendered on the Run page, on Compare, and inside a
    pain-point card, and only the first has a canvas. Naming the card would have been the
    same unkept promise in two places out of three.
    """
    from ai_backend.pipelines.grounding import ungrounded_answer

    for documents, web in ((False, True), (True, True)):
        text = ungrounded_answer(documents=documents, web=web)
        assert "what it returned" not in text, (
            "the refusal claims to show what the search returned, and an uncited answer "
            "has nothing to show"
        )
        assert "trace" in text, (
            "the refusal does not say where the evidence actually is, so a student has "
            "no way to check whether the search really came back empty"
        )
        assert "Search card" not in text, (
            "the refusal names the canvas's Search card, which is not on screen on "
            "Compare or inside a pain-point card — the same unkept promise it replaced"
        )


def test_the_answer_template_marks_web_citations_apart() -> None:
    """"web citations are visually distinguishable from document citations".

    Asserted against the stylesheet and the template contract, because this criterion
    is about what a student *sees*. Before the web route the property was structural —
    web results were impossible — so this markup is now the only thing enforcing it.

    Checked here rather than by driving a live web-routed answer, which would need a
    real model willing to route to the web: the guarantee is that the renderer
    distinguishes the kinds, and that is a property of the template and CSS.

    Synchronous, so reading these files off disk is not doing blocking I/O inside an
    event loop — there is no client call to make, and the assertions are about source
    files rather than about a response.
    """
    css = (REPO_ROOT / "frontend" / "static" / "app.css").read_text(encoding="utf-8")

    # A `data-kind` hook exists and web is styled apart from document.
    assert '[data-kind="web"]' in css, "web citations are not styled distinctly"
    # Not colour alone: there is a spelled-out badge class too.
    assert ".citations__kind" in css

    template = (REPO_ROOT / "frontend" / "templates" / "_answer.html").read_text(
        encoding="utf-8"
    )
    assert 'data-kind="{{ citation.kind' in template
    assert "citations__kind" in template

    # The URL is rendered as text, never as an anchor — Axis never fetches a result
    # URL and the panel should not invite the student to either.
    #
    # Jinja comments are stripped first. Without that, this assertion matched the
    # comment in the template *explaining* the rule, so it would have passed for a
    # template that documented the intent and then linked anyway.
    markup = re.sub(r"\{#.*?#\}", "", template, flags=re.DOTALL)
    assert "<a " not in markup, "a citation is rendered as a link"


# ── The student's toggle ──────────────────────────────────────────────────────
#
# Configuring a provider makes the web route *available*. Asking for it is a separate
# act, and off is the default: a web call is paid, goes to a third party, and carries
# the prompt-injection exposure of System Design Section 6.5.
#
# The distinction the tests below turn on is capability versus permission. Capability is
# `AXIS_SEARCH__PROVIDER`, read server-side at startup. Permission is a browser-supplied
# flag. They are combined with `and`, so permission can only ever narrow — which is what
# makes it safe for the second to come from a cookie.


async def test_the_toggle_off_offers_the_model_no_web_tool(step_store) -> None:
    """Off must look identical to never having configured a provider.

    Not merely "the web is not used": the model must not be *told* the tool exists.
    A model offered a tool it cannot use calls it confidently on every iteration, and
    the trace then shows empty results with nothing saying why — the same failure the
    no-provider case was written to avoid.
    """
    from ai_backend.contracts.pipeline import QueryContext
    from ai_backend.pipelines.agentic_rag import AgenticRagPipeline

    llm = FakeLLMProvider(
        responses=[
            "SOURCE: DOCUMENTS\nCOMPLEXITY: SIMPLE\nCONFIDENCE: 0.9\nREASON: internal",
            "",
            "Nothing found.",
        ]
    )
    search = FakeSearchProvider()
    pipeline = AgenticRagPipeline(
        retriever=_EmptyRetriever(), llm=llm, top_k=5, search=search
    )
    ctx = QueryContext(
        session_id="s1",
        strategy=Strategy.AGENTIC_RAG,
        question="How long is parental leave?",
        budget=_budget(),
        web_enabled=False,
    )

    with trace_context(session_id="s1", trace_id=ctx.trace_id):
        await pipeline.run(ctx)

    assert search.call_count == 0, "the provider was reached with the toggle off"
    # The router was never asked to consider a source the query had declined.
    route = next(s for s in step_store.all_steps if s.step_type.value == "route")
    assert route.attributes["web_available"] is False, route.attributes
    # And the loop offered one tool, not two.
    offered = {name for offered in llm.tools_offered for name in offered}
    assert SEARCH_WEB not in offered, offered


async def test_the_toggle_off_refuses_the_call_the_model_makes_anyway(
    step_store,
) -> None:
    """The enforcement, as distinct from the hint.

    Omitting a spec is a hint. A model can emit a tool call for anything, including a
    tool it was never offered — `_run_tool` already has a branch for exactly that, and
    this is the test that the toggle lands *on that branch* rather than on the web tool
    the pipeline is still holding.

    Without this, the toggle would be a prompt-level suggestion protecting a paid
    third-party call, which is not a control.
    """
    from ai_backend.contracts.models import ToolCall
    from ai_backend.contracts.pipeline import QueryContext
    from ai_backend.pipelines.agentic_rag import AgenticRagPipeline

    llm = FakeLLMProvider(
        responses=[
            "SOURCE: DOCUMENTS\nCOMPLEXITY: SIMPLE\nCONFIDENCE: 0.9\nREASON: internal",
            "",
            "Nothing found.",
        ],
        tool_calls=[
            [],
            # The model reaches for the web regardless of what it was offered.
            [ToolCall(id="tc1", name=SEARCH_WEB, arguments={"query": "anything"})],
            [],
        ],
    )
    search = FakeSearchProvider()
    pipeline = AgenticRagPipeline(
        retriever=_EmptyRetriever(), llm=llm, top_k=5, search=search
    )
    ctx = QueryContext(
        session_id="s1",
        strategy=Strategy.AGENTIC_RAG,
        question="What shipped this year?",
        budget=_budget(),
        web_enabled=False,
    )

    with trace_context(session_id="s1", trace_id=ctx.trace_id):
        await pipeline.run(ctx)

    assert search.call_count == 0, (
        "a hallucinated search_web reached the provider with the toggle off — the "
        "toggle is a prompt hint rather than a control"
    )
    # And the attempt is visible rather than swallowed, so a student can see the agent
    # tried and was refused.
    tool_steps = [s for s in step_store.all_steps if s.step_type.value == "call_tool"]
    assert tool_steps, "the refused call left no trace"
    assert any(s.attributes.get("unknown_tool") for s in tool_steps), [
        s.attributes for s in tool_steps
    ]


async def test_permission_cannot_conjure_a_provider_that_was_never_configured() -> None:
    """The security property, stated as a test.

    `web_enabled` arrives from a browser cookie. It is combined with the configured
    provider using `and`, so the worst a forged value can do is decline a route — it
    can never reach the internet on an install that configured none.
    """
    from ai_backend.contracts.pipeline import QueryContext
    from ai_backend.pipelines.agentic_rag import AgenticRagPipeline

    llm = FakeLLMProvider(
        responses=[
            "COMPLEXITY: SIMPLE\nCONFIDENCE: 0.9\nREASON: internal",
            "",
            "Nothing found.",
        ]
    )
    pipeline = AgenticRagPipeline(
        retriever=_EmptyRetriever(), llm=llm, top_k=5, search=None
    )
    ctx = QueryContext(
        session_id="s1",
        strategy=Strategy.AGENTIC_RAG,
        question="What shipped this year?",
        budget=_budget(),
        web_enabled=True,
    )

    with trace_context(session_id="s1", trace_id=ctx.trace_id):
        answer = await pipeline.run(ctx)

    assert answer is not None
    offered = {name for offered in llm.tools_offered for name in offered}
    assert SEARCH_WEB not in offered, offered


async def test_the_web_route_is_offered_as_a_control_and_starts_off(
    client: httpx.AsyncClient,
) -> None:
    """The toggle is how "web search is opt-in" becomes visible.

    Before it, the only way to answer "will this question reach the internet?" was to
    read the instructor's environment variables. Configuring a provider is the
    deployment's decision that the route may exist; this is the student's decision to
    use it, and the two are different questions.
    """
    page = (await client.get("/")).text

    assert 'action="/websearch"' in page, "the web route has no control"
    # Off is the default, and it is the pressed one on a fresh session.
    off = re.search(r'name="on" value="0"[^>]*aria-pressed="true"', page)
    assert off, "the web route does not start off"
    assert 'name="on" value="1"[^>]*aria-pressed' not in page


async def test_the_control_is_absent_when_no_provider_is_configured(settings) -> None:
    """A switch that cannot switch anything on is worse than no switch.

    It invites "I turned it on, why is nothing happening?" — which is not a question
    the demo exists to answer, and the answer is in an environment variable the student
    cannot see. The capability reaches the page through `/health`.
    """
    from ai_backend.config.settings import Settings

    assert Settings().search.provider == "none", (
        "web search must stay opt-in at the deployment level"
    )
    assert settings.search.provider == "fake", (
        "the suite needs a provider; without one the toggle tests assert nothing"
    )


async def test_choosing_the_web_route_works_without_javascript(
    client: httpx.AsyncClient,
) -> None:
    """A form post and a redirect, like Pace.

    The one control in the sidebar that spends money must not need a script — and the
    choice has to survive a reload, because the reason to set it is that a room is
    watching.
    """
    on = await client.post("/websearch", data={"on": "1"}, follow_redirects=False)
    assert on.status_code == 303, on.text

    page = (await client.get("/")).text
    assert re.search(r'name="on" value="1"[^>]*aria-pressed="true"', page), (
        "the choice did not survive the redirect"
    )

    await client.post("/websearch", data={"on": "0"}, follow_redirects=False)
    back = (await client.get("/")).text
    assert re.search(r'name="on" value="0"[^>]*aria-pressed="true"', back)


async def test_an_unparseable_toggle_reads_as_off(client: httpx.AsyncClient) -> None:
    """The cookie is user-editable and decides whether a paid call may happen.

    So it is read as a whitelist rather than as truthiness: `"true"`, `"yes"` and
    `"0"` are all strings a lenient parse would have taken for yes at least once.
    """
    from frontend.app import _web_search

    class _Req:
        def __init__(self, value):
            self.cookies = {"axis_web": value} if value is not None else {}

    assert _web_search(_Req("1")) is True
    for value in ("true", "yes", "on", "0", "", "01", None):
        assert _web_search(_Req(value)) is False, value
