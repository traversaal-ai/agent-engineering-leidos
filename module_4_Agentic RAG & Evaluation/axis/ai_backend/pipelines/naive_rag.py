"""Naive RAG — the baseline, and half of the only comparison Axis makes.

Retrieve once, generate once. **Exactly two steps, and the absence of the others
is load-bearing:** `test_strategy_emits_the_step_types_its_shape_implies[naive_rag]`
asserts no `route` and no `decompose` appear in the trace. That absence is how the
single-shot side of the comparison becomes observable rather than asserted — a student
reading this trace beside Agentic RAG's sees the difference as structure, not as a
claim in a slide.

**It gets the same `Retriever` instance Agentic RAG does**, which is the experiment's
control: if the baseline retrieved differently, no difference between the two answers
could be attributed to the orchestration. It is typed as the protocol rather than as
`VectorRetriever` so this pipeline cannot reach into Chroma and quietly acquire a
capability its comparator lacks.
"""

from __future__ import annotations

from ai_backend.agents.spend import QuerySpend
from ai_backend.contracts.models import (
    Answer,
    RetrievedContext,
    StepType,
    Strategy,
)
from ai_backend.contracts.pipeline import QueryContext
from ai_backend.contracts.providers import LLMProvider
from ai_backend.contracts.retriever import Retriever
from ai_backend.observability.trace import atrace_step

# The grounding contract — prompt, sentinel, refusal text, citation resolution — is
# shared with every other strategy. See `grounding.py` for why it is not defined
# here any more.
from ai_backend.pipelines.grounding import (
    MAX_ANSWER_TOKENS,
    NO_CONTENT_SENTINEL,
    UNGROUNDED_ANSWER,
    augment,
    resolve_citations,
    passages_from,
)

TOP_K = 5


class NaiveRagPipeline:
    """Single-shot retrieval-augmented generation."""

    strategy = Strategy.NAIVE_RAG

    def __init__(self, *, retriever: Retriever, llm: LLMProvider, top_k: int = TOP_K) -> None:
        self._retriever = retriever
        self._llm = llm
        self._top_k = top_k

    async def run(self, ctx: QueryContext) -> Answer:
        context = await self._retriever.retrieve(
            ctx.question, session_id=ctx.index_scope, top_k=self._top_k
        )

        if context.is_empty:
            return await self._ungrounded(ctx, context)

        return await self._synthesize(ctx, context, QuerySpend(ctx.budget, llm=self._llm))

    # -- the grounded path -------------------------------------------------

    async def _synthesize(
        self, ctx: QueryContext, context: RetrievedContext, spend: QuerySpend
    ) -> Answer:
        # Documents only, always. Naive RAG has no router and no web tool — it is the
        # baseline the agentic path is measured against, and a baseline with access to
        # a source its comparator lacks is not a baseline (System Design Section 4).
        passages = passages_from(context.chunks, [])
        messages = await augment(
            ctx.question, passages, strategy=self.strategy.value
        )

        async with atrace_step(
            StepType.SYNTHESIZE,
            label="NaiveRagPipeline.synthesize",
            raw_input=ctx.question,
            attributes={"passages": len(context.chunks)},
        ) as step:
            # Guards this individual call, which the Backend's query-level cap does
            # not. Naive RAG makes exactly one, so the accumulator is doing nothing
            # a plain check would not — it is here so both pipelines enforce the cap
            # through the same code, and neither can drift from the other.
            spend.reserve_for(messages, max_completion_tokens=MAX_ANSWER_TOKENS)
            completion = await self._llm.complete(
                messages, max_tokens=MAX_ANSWER_TOKENS, temperature=0.0
            )
            spend.record(completion.usage)
            step.add_usage(completion.usage)

            # The model can decide, having seen the passages, that none of them
            # actually answer the question — a stricter judgement than the
            # similarity threshold could make, and worth honouring.
            if NO_CONTENT_SENTINEL in completion.text:
                step.set_attribute("grounded", False)
                step.set_output("model reported no relevant content in the passages")
                return Answer(
                    text=UNGROUNDED_ANSWER,
                    strategy=self.strategy,
                    trace_id=ctx.trace_id,
                    citations=[],
                    grounded=False,
                    usage=context.usage + completion.usage,
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
                # The model answered but cited nothing we can verify, so the
                # answer is unattributable. Presenting it anyway is the exact
                # failure PRD Section 6 forbids — an answer a student would
                # reasonably take as grounded, with no source to check.
                #
                # Nothing is concealed by declining to show it: `set_output` above
                # has already put the model's raw text in the trace, so a student
                # can see what it said and that Axis refused to vouch for it.
                # That is more instructive than the answer would have been.
                step.set_attribute("grounded", False)
                step.set_attribute("withheld_uncited_answer", True)
                return Answer(
                    text=UNGROUNDED_ANSWER,
                    strategy=self.strategy,
                    trace_id=ctx.trace_id,
                    citations=[],
                    grounded=False,
                    usage=context.usage + completion.usage,
                )

            return Answer(
                text=answer_text,
                strategy=self.strategy,
                trace_id=ctx.trace_id,
                citations=citations,
                grounded=True,
                usage=context.usage + completion.usage,
            )

    # -- the ungrounded path ----------------------------------------------

    async def _ungrounded(self, ctx: QueryContext, context: RetrievedContext) -> Answer:
        """Nothing cleared the relevance threshold.

        **No LLM call is made.** Asking a model to answer from no context is
        precisely how a confident, fabricated citation gets produced — which PRD
        Section 6 forbids by name. It is also free, which matters when a student
        asks five off-topic questions in a row.

        The step is still emitted, because Section 11 requires the empty
        retrieval be visible in the trace rather than inferred from a short answer.
        """
        async with atrace_step(
            StepType.SYNTHESIZE,
            label="NaiveRagPipeline.synthesize",
            raw_input=ctx.question,
            attributes={"passages": 0, "grounded": False, "llm_called": False},
        ) as step:
            step.set_output(
                "No sufficiently relevant content found — answered without an LLM "
                "call rather than risk an ungrounded answer."
            )

        return Answer(
            text=UNGROUNDED_ANSWER,
            strategy=self.strategy,
            trace_id=ctx.trace_id,
            citations=[],
            grounded=False,
            usage=context.usage,
        )
