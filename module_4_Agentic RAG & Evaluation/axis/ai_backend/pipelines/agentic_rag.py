"""Agentic RAG — the orchestrated half of the comparison.

Route, decompose, retrieve per sub-question, escalate where retrieval failed,
synthesise once. The presence of `route` and `decompose` is load-bearing in exactly
the way their absence is in `naive_rag.py`:
`test_strategy_emits_the_step_types_its_shape_implies` asserts both appear here and
neither appears there. That contrast is the whole comparison made observable — a
student reading the two traces sees a difference in structure, not a claim on a
slide.

**It holds the same `Retriever` instance the baseline does**, typed as the protocol
rather than as `VectorRetriever`. Everything this pipeline adds sits *above* retrieval,
which is what makes the cost and latency delta a measurement of orchestration rather
than of two different searches.

Cost, for the comparison this all exists to serve: three LLM calls in the common
case (route, decompose, synthesize) against Naive RAG's one, plus one per escalated
sub-question. The synthesis call is always held in reserve, so a query that explores
too eagerly returns a partial answer rather than no answer.
"""

from __future__ import annotations

from ai_backend.agents.cache import CacheHit, SemanticCache
from ai_backend.agents.decomposer import Decomposer
from ai_backend.agents.react import Mode, ReActLoop
from ai_backend.agents.rewriter import Rewrite, Rewriter
from ai_backend.agents.router import RouteDecision, Router, Source
from ai_backend.agents.spend import QuerySpend
from ai_backend.agents.tools import DocumentSearchTool, WebSearchTool
from ai_backend.contracts.models import (
    Answer,
    Chunk,
    RetrievedContext,
    StepType,
    Strategy,
    Usage,
    WebSource,
)
from ai_backend.contracts.pipeline import QueryContext
from ai_backend.contracts.providers import (
    EmbeddingProvider,
    LLMProvider,
    SearchProvider,
)
from ai_backend.contracts.retriever import Retriever
from ai_backend.errors import BudgetExceededError
from ai_backend.observability.trace import atrace_step
from ai_backend.pipelines.grounding import (
    MAX_ANSWER_TOKENS,
    NO_CONTENT_SENTINEL,
    augment,
    dedupe_chunks,
    resolve_citations,
    passages_from,
    ungrounded_answer,
)

TOP_K = 5

# The synthesis prompt gets every sub-question's passages, so the per-retrieval
# `top_k` alone is not a bound on prompt size. Four sub-questions at top_k=5 is 20
# passages, which is both expensive and worse than a focused set — a model given 20
# passages cites the wrong one more often than a model given 8.
MAX_SYNTHESIS_PASSAGES = 8

# Web results get their own allowance rather than sharing the one above. Fewer,
# because a search snippet is a couple of sentences where a chunk is a paragraph, and
# because the marginal fourth search result is rarely worth the prompt space — search
# engines front-load relevance far more aggressively than a similarity threshold does.
MAX_SYNTHESIS_WEB_RESULTS = 4


class AgenticRagPipeline:
    """Router + decomposer + bounded ReAct loop over vector retrieval."""

    strategy = Strategy.AGENTIC_RAG

    def __init__(
        self,
        *,
        retriever: Retriever,
        llm: LLMProvider,
        embeddings: EmbeddingProvider | None = None,
        top_k: int = TOP_K,
        search: SearchProvider | None = None,
        cache: SemanticCache | None = None,
        rewrite_enabled: bool = True,
    ) -> None:
        self._retriever = retriever
        self._llm = llm
        self._top_k = top_k
        self._search = search
        # The cache needs to embed a question to compare it, and the pipeline has no
        # other use for an embedding provider — retrieval embeds its own query
        # inside the `Retriever`. Both are optional so every existing construction
        # keeps working: with either absent the cache is simply never consulted,
        # which is the same as `AXIS_CACHE__ENABLED=false`.
        self._embeddings = embeddings
        self._cache = cache if embeddings is not None else None
        self._rewrite_enabled = rewrite_enabled
        # The Router and the loop are both told whether the web exists, rather than
        # each deciding for itself. If they disagreed — a router routing to WEB while
        # the loop had no web tool — the run would report a source it never reached.
        # Both are constructed with the capability and told the *effective* value per
        # query in `run` — see the comment there. Constructing them with it keeps a
        # sensible default for any caller that uses them directly.
        self._rewriter = Rewriter(llm=llm)
        self._router = Router(llm=llm, web_available=search is not None)
        self._decomposer = Decomposer(llm=llm)
        self._loop = ReActLoop(
            llm=llm,
            tool=DocumentSearchTool(retriever=retriever, top_k=top_k),
            web=WebSearchTool(provider=search) if search is not None else None,
        )

    async def run(self, ctx: QueryContext) -> Answer:
        # One accumulator for the whole query. Every LLM call in every component
        # reserves against this, which is what makes the cost cap hold across a
        # pipeline that makes more than one call.
        spend = QuerySpend(ctx.budget, llm=self._llm)

        # **Computed once, here, and given to both.** Capability — is a provider
        # configured at all — and permission — did the student leave the toggle on —
        # combined into one value before either component is used.
        #
        # The one-place rule is what keeps the Router and the loop from disagreeing: a
        # Router that routes to WEB while the loop has no web tool reports a source the
        # run never reached. That risk is the reason this used to be fixed at
        # construction; fixing it at construction is not what avoids the risk, deciding
        # it once per query is.
        web = self._search is not None and ctx.web_enabled

        # ── The cache, and the ordering decision it forces ──────────────────
        #
        # A question with no history is looked up **as typed**, before anything is
        # spent. A follow-up is not: "How long is it?" keyed on its own words would
        # match a previous "How long is it?" about something else entirely and serve
        # the wrong answer with a straight face. So with history, the rewriter runs
        # first and the cache is keyed on the resolved question.
        #
        # This diverges from chapter 07, which always keys on the raw query — see
        # `docs/Axis_Notebook_Alignment.md` §9. The cost of the divergence is exactly
        # one rewrite call on the first turn of a conversation that would have hit;
        # the cost of *not* diverging is an answer to a question nobody asked.
        rewrite: Rewrite | None = None
        if ctx.history:
            rewrite = await self._rewrite(ctx, spend=spend)
            hit = await self._lookup(ctx, rewrite.text, spend=spend, keyed_on="rewritten")
        else:
            hit = await self._lookup(ctx, ctx.question, spend=spend, keyed_on="raw")

        if hit is not None:
            # Returned here, so `route`, `decompose`, `retrieve`, `augment` and
            # `synthesize` are never emitted. The absence is the lesson — the
            # question did not enter the pipeline — and the canvas greys the
            # answering track out rather than drawing stages that did not happen.
            return hit.answer.model_copy(update={"trace_id": ctx.trace_id})

        if rewrite is None:
            rewrite = await self._rewrite(ctx, spend=spend)

        # **Everything downstream sees the rewritten question.** The router and the
        # decomposer included: routing on text whose abbreviations are expanded and
        # whose pronouns are resolved is strictly better information for the same
        # money. chapter 07 routes on the raw query and applies the rewrite only to
        # decomposition, which reads as an oversight rather than a decision.
        question = rewrite.text

        decision = await self._router.route(question, spend=spend, web_available=web)
        sub_questions = await self._decomposer.decompose(
            question,
            spend=spend,
            needed=decision.needs_decomposition,
            reason=decision.reason,
        )

        context = await self._gather(
            ctx,
            sub_questions,
            source=decision.source,
            spend=spend,
            web=web,
            multi_hop=decision.multi_hop,
        )

        if context.is_empty:
            return await self._ungrounded(
                ctx, context, sub_questions, decision=decision, spend=spend
            )

        answer = await self._synthesize(
            ctx, context, sub_questions, decision=decision, spend=spend
        )
        # Stored under the question the *cache* will be asked about next time, which
        # is the same key the lookup above used. Storing the raw wording of a
        # follow-up would file this answer under "How long is it?" and hand it to
        # the next unrelated "it".
        await self._remember(ctx, question, answer)
        return answer

    # -- the three stages in front of routing ------------------------------

    async def _rewrite(self, ctx: QueryContext, *, spend: QuerySpend) -> Rewrite:
        return await self._rewriter.rewrite(
            ctx.question,
            spend=spend,
            history=ctx.history,
            enabled=self._rewrite_enabled,
        )

    async def _lookup(
        self, ctx: QueryContext, question: str, *, spend: QuerySpend, keyed_on: str
    ) -> CacheHit | None:
        """Ask the cache, if there is one. Costs one embedding on a miss or a hit."""
        if self._cache is None or self._embeddings is None:
            return None
        return await self._cache.lookup(
            question,
            # The **scope**, not the session. A cached answer is an answer about a
            # particular corpus, so each corpus gets its own cache — which makes
            # switching correct by construction rather than by remembering to
            # invalidate, and lets a student switch back and still find their
            # earlier answers stored.
            scope=ctx.index_scope,
            embeddings=self._embeddings,
            enabled=ctx.cache_enabled,
            keyed_on=keyed_on,
        )

    async def _remember(self, ctx: QueryContext, question: str, answer: Answer) -> None:
        if self._cache is None or self._embeddings is None or not ctx.cache_enabled:
            return
        await self._cache.store(
            question, answer, scope=ctx.index_scope, embeddings=self._embeddings
        )

    # -- retrieval ---------------------------------------------------------

    async def _gather(
        self,
        ctx: QueryContext,
        sub_questions: list[str],
        *,
        source: Source,
        spend: QuerySpend,
        web: bool,
        multi_hop: bool = False,
    ) -> RetrievedContext:
        """Retrieve per sub-question, from whichever source the router chose.

        The document retrieval is attempted first and unconditionally whenever the
        route includes documents, because it is cheap (one embedding) and usually
        sufficient. The loop costs an LLM call, so it runs only where the cheap path
        failed — or, on a `WEB` route, where there was no cheap path to try.

        **A `WEB` route still goes through the loop rather than calling the search
        provider directly.** Two reasons: the model gets to phrase the search query,
        which is the actual agentic decision and is lost if the pipeline just passes
        the sub-question through verbatim; and the search then sits inside the same
        bounded, budget-checked, traced path as everything else, instead of a second
        path that has to re-implement all three.
        """
        gathered = RetrievedContext()

        for sub_question in sub_questions:
            direct = RetrievedContext()
            if source.uses_documents:
                direct = await self._retriever.retrieve(
                    sub_question, session_id=ctx.index_scope, top_k=self._top_k
                )
                # **The multi-hop branch, and it is one condition.** On a
                # documents-only route a successful search is normally the end of
                # it; on a hop chain it is the *beginning*, because what it found is
                # what names the next thing to look for. So the short-circuit is
                # skipped and the loop is entered with those passages seeded in.
                #
                # Guarded by the router's decision rather than by anything about the
                # retrieval, which is what keeps every `SINGLE` run behaving exactly
                # as it did before hops existed.
                if not direct.is_empty and source is Source.DOCUMENTS and not multi_hop:
                    gathered = _merge(gathered, direct)
                    continue

            explored = await self._loop.resolve(
                sub_question,
                # The loop's document tool retrieves, so it needs the scope too —
                # otherwise an escalation would search both corpora after the direct
                # search had searched one.
                session_id=ctx.index_scope,
                spend=spend,
                budget=ctx.budget,
                web_allowed=web,
                mode=Mode.HOP if multi_hop and not direct.is_empty else Mode.ESCALATE,
                found=direct,
            )
            gathered = _merge(gathered, _merge(direct, explored))

        return gathered

    # -- the grounded path -------------------------------------------------

    async def _synthesize(
        self,
        ctx: QueryContext,
        context: RetrievedContext,
        sub_questions: list[str],
        *,
        decision: RouteDecision,
        spend: QuerySpend,
    ) -> Answer:
        # Deduplicated because two sub-questions about one document routinely return
        # the same chunk, and showing it twice produces citations that look like two
        # sources and are one.
        chunks = _rank(dedupe_chunks(context.chunks))[:MAX_SYNTHESIS_PASSAGES]
        # Web results get their own share of the prompt rather than competing with
        # documents for one budget. On a `BOTH` route a single pooled cap would let
        # eight document chunks crowd the web results out entirely, and the answer
        # would silently be a documents-only answer on a query the router said needed
        # both — which is worse than either, because the trace would say "web" and
        # the citations would not.
        sources = _dedupe_sources(context.sources)[:MAX_SYNTHESIS_WEB_RESULTS]
        passages = passages_from(chunks, sources)
        messages = await augment(
            ctx.question, passages, strategy=self.strategy.value
        )

        async with atrace_step(
            StepType.SYNTHESIZE,
            label="AgenticRagPipeline.synthesize",
            raw_input=ctx.question,
            attributes={
                "passages": len(passages),
                "passages_before_dedupe": len(context.chunks) + len(context.sources),
                "document_passages": len(chunks),
                "web_passages": len(sources),
                "sub_questions": len(sub_questions),
                "source": decision.source.value,
            },
        ) as step:
            try:
                spend.reserve_for(messages, max_completion_tokens=MAX_ANSWER_TOKENS)
            except BudgetExceededError:
                # The loop reserves a call for synthesis, so reaching here means the
                # query was admitted with less budget than one answer costs. That is
                # a refusal, not a partial result — and it must reach the student as
                # a clear message rather than an empty answer.
                step.mark_budget_exceeded("no budget remained for the final answer")
                raise

            completion = await self._llm.complete(
                messages, max_tokens=MAX_ANSWER_TOKENS, temperature=0.0
            )
            spend.record(completion.usage)
            step.add_usage(completion.usage)
            step.set_attribute("llm_calls_this_query", spend.llm_calls)
            step.set_attribute("tool_calls_this_query", spend.tool_calls)

            # Every LLM call this query made, not just this one. Routing and
            # decomposition are real spend, and omitting them made an agentic run
            # report exactly Naive RAG's cost — which the golden set caught, both
            # strategies reporting $0.0023 to the cent. It would have under-charged
            # the session cap and made Compare mode's central claim unfalsifiable.
            total = context.usage + spend.usage

            if NO_CONTENT_SENTINEL in completion.text:
                step.set_attribute("grounded", False)
                step.set_output("model reported no relevant content in the passages")
                return self._answer(
                    ctx,
                    _refusal(decision, spend),
                    [],
                    grounded=False,
                    usage=total,
                )

            # Text and citations from one walk, so the markers in the prose and
            # the numbers on the list cannot disagree. They did: the list is built
            # in order of first appearance and rendered from its own loop index, so
            # a model writing "[1] ... [4]" produced prose citing [4] beside a list
            # whose second entry was labelled [2].
            answer_text, citations = resolve_citations(completion.text, passages)
            step.set_attribute("citations", len(citations))
            step.set_output(completion.text)

            if not citations:
                # Same refusal as Naive RAG's, and deliberately identical: an
                # uncited answer is unattributable regardless of how much work went
                # into producing it. An agentic pipeline that relaxed this to show
                # off its effort would be the more dangerous of the two.
                step.set_attribute("grounded", False)
                step.set_attribute("withheld_uncited_answer", True)
                return self._answer(
                    ctx,
                    _refusal(decision, spend),
                    [],
                    grounded=False,
                    usage=total,
                )

            return self._answer(
                ctx, answer_text, citations, grounded=True, usage=total
            )

    # -- the ungrounded path ----------------------------------------------

    async def _ungrounded(
        self,
        ctx: QueryContext,
        context: RetrievedContext,
        sub_questions: list[str],
        *,
        decision: RouteDecision,
        spend: QuerySpend,
    ) -> Answer:
        """Every sub-question came back empty, and the loop could not fix it.

        **No LLM call.** Asking a model to answer from no context is how a
        confident fabricated citation appears, which PRD Section 6 forbids by name.
        The step is still emitted, because Section 11 requires the empty retrieval
        be visible rather than inferred from a short answer — and here it carries
        the sub-questions, so a student can see the decomposition was attempted and
        what it looked for.
        """
        async with atrace_step(
            StepType.SYNTHESIZE,
            label="AgenticRagPipeline.synthesize",
            raw_input=ctx.question,
            attributes={
                "passages": 0,
                "grounded": False,
                "llm_called": False,
                "sub_questions": len(sub_questions),
                "source": decision.source.value,
            },
        ) as step:
            step.set_output(
                "No sufficiently relevant content found for any sub-question — "
                "answered without an LLM call rather than risk an ungrounded "
                "answer. Searched for: " + "; ".join(sub_questions)
            )

        # Routing, decomposition and any escalation already happened, so this
        # "answered without an LLM call" path is not free. Reporting only the
        # retrieval cost would make a failed agentic query look cheaper than a
        # failed naive one, which is backwards.
        return self._answer(
            ctx,
            _refusal(decision, spend),
            [],
            grounded=False,
            usage=context.usage + spend.usage,
        )

    def _answer(
        self, ctx: QueryContext, text: str, citations, *, grounded: bool, usage: Usage
    ) -> Answer:
        return Answer(
            text=text,
            strategy=self.strategy,
            trace_id=ctx.trace_id,
            citations=citations,
            grounded=grounded,
            usage=usage,
        )


def _refusal(decision: RouteDecision, spend: QuerySpend) -> str:
    """What to say when nothing usable was found, worded from what was searched.

    **The two halves come from different places on purpose.** The documents half is
    the router's decision, because a `DOCUMENTS` or `BOTH` route always attempts a
    retrieval in `_gather` — it is unconditional there, so the intention and the act
    cannot diverge. The web half is `spend.search_calls`, which counts searches that
    actually completed, because on that side they routinely do diverge: the agent can
    answer a `WEB` question out of documents, or exhaust `max_search_calls_per_query`
    before a call is made. Claiming a paid third-party search Axis never made would
    be the same failure this function exists to fix, pointed the other way.
    """
    return ungrounded_answer(
        documents=decision.source.uses_documents, web=spend.search_calls > 0
    )


def _rank(chunks: list[Chunk]) -> list[Chunk]:
    """Best-scoring first, so truncation drops the weakest passages.

    Without this, `[:MAX_SYNTHESIS_PASSAGES]` would keep whatever the first
    sub-questions happened to return and discard a later sub-question's better
    material — making the answer depend on decomposition order.
    """
    return sorted(chunks, key=lambda c: c.score or 0.0, reverse=True)


def _merge(left: RetrievedContext, right: RetrievedContext) -> RetrievedContext:
    return RetrievedContext(
        chunks=[*left.chunks, *right.chunks],
        sources=[*left.sources, *right.sources],
        usage=left.usage + right.usage,
    )


def _dedupe_sources(sources: list[WebSource]) -> list[WebSource]:
    """Collapse repeated web results, keeping first appearance.

    Two sub-questions about the same topic routinely surface the same page, and the
    same URL numbered twice produces citations that look like two sources and are
    one — the same failure `dedupe_chunks` exists to prevent on the document side.
    Keyed on URL rather than on the snippet, because a search engine returns
    slightly different snippets for the same page across queries.
    """
    seen: set[str] = set()
    out: list[WebSource] = []
    for source in sources:
        key = source.url or source.snippet
        if key in seen:
            continue
        seen.add(key)
        out.append(source)
    return out
