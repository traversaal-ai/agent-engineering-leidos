"""The AI Backend's own composition root.

This module exists because of a boundary violation the architecture test caught.
The wiring — build the providers, build the vector store, construct the retriever,
register the pipelines — first lived in `backend/dispatch.py`, and
`tests/unit/test_layer_boundaries.py` failed: the Backend layer was naming Chroma,
`VectorRetriever`, and `NaiveRagPipeline` directly.

The test was right, and not on a technicality. CLAUDE.md says the Backend
"contains no retrieval or generation logic", and a module that decides *which
retriever exists* is making a retrieval decision even if it never calls one. It
would also mean every future milestone edits a Backend file to add an AI Backend
component, which is exactly the erosion the rule guards against.

So the AI Backend assembles itself, and the Backend asks for one object. The
Backend now names no implementation at all — only `build_runtime` and the
contracts.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ai_backend.agents.cache import SemanticCache
from ai_backend.config.settings import TOOL_CAPABLE_PROVIDERS, Settings
from ai_backend.contracts.models import AgentStep, Strategy
from ai_backend.contracts.pipeline import QueryBudget
from ai_backend.contracts.providers import (
    EmbeddingProvider,
    LLMProvider,
    VisionProvider,
)
from ai_backend.contracts.retriever import Retriever
from ai_backend.errors import ConfigurationError
from ai_backend.ingestion.chunker import ChunkingConfig
from ai_backend.ingestion.pipeline import IngestionResult, ingest_document
from ai_backend.observability.narrate import narrate
from ai_backend.pipelines import mark_unavailable, register
from ai_backend.pipelines.agentic_rag import AgenticRagPipeline
from ai_backend.pipelines.naive_rag import NaiveRagPipeline
from ai_backend.providers import (
    build_embedding_provider,
    build_llm_provider,
    build_search_provider,
    build_vision_provider,
)
from ai_backend.retrievers.store import (
    ChromaVectorStore,
    InMemoryVectorStore,
    VectorStore,
)
from ai_backend.retrievers.vector import VectorRetriever
from ai_backend.summarize import Summary, summarize_session

logger = logging.getLogger("axis.runtime")


class AiRuntime:
    """Long-lived AI Backend collaborators, built once per process.

    Providers, the vector store, and the retriever are constructed here and held
    for the process lifetime: an HTTP client and a Chroma client are both too
    expensive to create per request.

    Constructing this also registers the strategy pipelines, so "which strategies
    are available" is a consequence of what was actually wired rather than a
    separate list that could disagree with reality.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.embeddings: EmbeddingProvider = build_embedding_provider(settings)
        self.llm: LLMProvider = build_llm_provider(settings)

        # Built on first use, not here. Constructing it raises for an Ollama
        # configuration (no captioning adapter exists), and an instructor who
        # never uploads an image should not be blocked by that. Deferring turns a
        # startup failure into a per-file upload failure, which is both accurate
        # and recoverable.
        self._vision: VisionProvider | None = None
        self._vision_error: ConfigurationError | None = None

        # `None` when `AXIS_SEARCH__PROVIDER=none`, which is the default. Built here
        # rather than deferred like vision, because unlike captioning it changes what
        # the Router is allowed to offer the model — and that has to be settled before
        # the first query, not discovered during one.
        self.search = build_search_provider(settings)

        self.store: VectorStore = _build_vector_store(settings)
        self.retriever: Retriever = VectorRetriever(
            store=self.store,
            embeddings=self.embeddings,
            hybrid=settings.retrieval.hybrid,
            min_similarity=settings.retrieval.min_similarity,
        )

        # Held here rather than inside the pipeline, for the same reason the store
        # and the retriever are: a pipeline is constructed per query (`register`
        # takes a factory), so a cache owned by one would be empty every time and
        # the feature would silently do nothing.
        #
        # `None` when `AXIS_CACHE__ENABLED=false`, which switches it off end to end
        # — the pipeline is handed no cache, the lookup step is never emitted, and
        # the canvas draws no cache band. The same shape as `search` above: a
        # capability that is absent rather than present-and-inert.
        self.cache: SemanticCache | None = (
            SemanticCache(
                min_similarity=settings.cache.min_similarity,
                max_entries=settings.cache.max_entries,
            )
            if settings.cache.enabled
            else None
        )

        self._register_pipelines()

    def invalidate_cache(self, scope: str) -> int:
        """Forget one corpus's cached answers. Returns how many were dropped.

        **Called after every successful ingest**, from `ingestion`'s caller, and
        that is correctness rather than tidiness: a cached answer is an answer about
        a particular corpus. Once another document is indexed, the same question may
        have a different right answer, and serving the stored one would be the cache
        actively making the system wrong.

        Takes a *scope*, not a session. Entries are keyed by scope, so indexing into
        one corpus leaves the other's answers alone — which is right, because nothing
        about them changed.
        """
        return self.cache.invalidate(scope) if self.cache else 0

    def forget_session(self, session_id: str) -> int:
        """Forget every corpus this session cached. For discarding a session."""
        return self.cache.invalidate_session(session_id) if self.cache else 0

    def _register_pipelines(self) -> None:
        """Fill both strategy slots.

        **Both get `self.retriever` — the same object, not two of a kind.** Sharing one
        retriever is what makes the comparison a measurement: two instances over two
        indexes would make every difference between the strategies ambiguous between
        retrieval and orchestration, which is the one thing the product exists to
        separate.
        """
        register(
            Strategy.NAIVE_RAG,
            lambda: NaiveRagPipeline(
                retriever=self.retriever,
                llm=self.llm,
                top_k=self.settings.retrieval.top_k,
            ),
        )
        if self.settings.llm.provider not in TOOL_CAPABLE_PROVIDERS:
            # Built, but unusable here. See `mark_unavailable` for why this is not a
            # refusal to boot: the non-agentic strategies work fine on this provider.
            mark_unavailable(
                Strategy.AGENTIC_RAG,
                f"AXIS_LLM__PROVIDER={self.settings.llm.provider!r} cannot call "
                f"tools, and an agent loop without tools is Naive RAG with extra "
                f"steps. Use openai or anthropic for the agentic strategies, or "
                f"select naive_rag.",
            )
            return

        register(
            Strategy.AGENTIC_RAG,
            lambda: AgenticRagPipeline(
                retriever=self.retriever,
                llm=self.llm,
                top_k=self.settings.retrieval.top_k,
                # `None` disables the web route end to end: the Router omits WEB from
                # its prompt and the loop omits the tool. Naive RAG is not given this
                # argument at all — it has no router to make the choice with, and a
                # baseline reaching a source its comparator cannot is not a baseline.
                search=self.search,
                # Nor is Naive RAG given these three, and for the same reason. The
                # baseline gets no rewriter, no cache and no memory: the whole point
                # of the comparison is that the agentic column has mechanisms the
                # baseline lacks, and a baseline that quietly acquired them would
                # make every measurement on the Why-agentic page meaningless.
                # Asserted by the step-shape and `test_the_baseline_never_*` tests.
                embeddings=self.embeddings,
                cache=self.cache,
                rewrite_enabled=self.settings.agent.rewrite_enabled,
            ),
        )

    @property
    def vision(self) -> VisionProvider | None:
        if self._vision is None and self._vision_error is None:
            try:
                self._vision = build_vision_provider(self.settings)
            except ConfigurationError as exc:
                logger.info("Image captioning unavailable: %s", exc.message)
                self._vision_error = exc
        return self._vision

    async def ingest(
        self,
        *,
        scope: str,
        document_id: str,
        filename: str,
        data: bytes,
        corpus: str = "",
    ) -> IngestionResult:
        """Index one document into one corpus.

        `scope` rather than `session_id`: the index is keyed by session *and*
        corpus (`contracts/pipeline.py::index_scope`), so what a document is indexed
        *into* is the same string retrieval will later search.

        `corpus` is the name alone, recorded on the trace so the canvas and the raw
        trace can tell which corpus a document belongs to. Redundant with `scope` and
        deliberately so: splitting the scope back apart in the reader would put the
        composition rule in two places.
        """
        return await ingest_document(
            document_id=document_id,
            filename=filename,
            data=data,
            session_id=scope,
            corpus=corpus,
            store=self.store,
            embeddings=self.embeddings,
            vision=self.vision,
            max_uncompressed_bytes=self.settings.upload.max_uncompressed_bytes,
            chunking=ChunkingConfig(
                max_chars=self.settings.retrieval.chunk_chars,
                overlap_chars=self.settings.retrieval.chunk_overlap_chars,
            ),
        )

    async def summarize(
        self,
        *,
        scope: str,
        budget: QueryBudget,
        filenames: dict[str, str] | None = None,
        document_ids: Sequence[str] | None = None,
    ) -> Summary:
        """A structured overview of one corpus, or of a chosen subset of it.

        On the runtime for the same reason `narrate` is: the Backend passes a scope
        and a budget and gets a result, without naming a provider or a store.
        `filenames` comes down from the Backend because the `document` table owns
        names (System Design Section 7) and the AI Backend indexes by id.

        `document_ids` is the Summarize page's checkboxes. `None` means everything —
        everything *in this corpus*, which is the reading that keeps the page's cost
        curve honest: summarizing is supposed to scale with the corpus, and a summary
        that silently read both would report a figure for documents the student was
        not looking at.
        """
        return await summarize_session(
            session_id=scope,
            store=self.store,
            llm=self.llm,
            budget=budget,
            filenames=filenames,
            document_ids=document_ids,
        )

    async def narrate(self, step: AgentStep) -> str:
        """Explain one recorded step in plain language.

        On the runtime rather than free-standing so the Backend never has to name a
        provider to ask for one — it passes a step and gets a sentence.
        """
        return await narrate(step, llm=self.llm)

    async def chunk_counts(self, scope: str) -> dict[str, int]:
        """Chunks per document, read from the index rather than the upload record.

        So the number reflects what retrieval can actually reach — a document that
        parsed but produced nothing indexable reports zero, which is what a
        student needs to see.
        """
        counts: dict[str, int] = {}
        for chunk in await self.store.all_chunks(session_id=scope):
            counts[chunk.document_id] = counts.get(chunk.document_id, 0) + 1
        return counts


def _build_vector_store(settings: Settings) -> VectorStore:
    """Chroma, or the in-memory store when there is nowhere to persist.

    A `:memory:` database path signals a throwaway process — the test suite, or a
    demo nobody wants leaving state behind — so the vector index should be equally
    throwaway rather than quietly writing to disk anyway.

    The embedding model is passed in because the index is keyed to it: switching
    provider mid-project is a normal thing to do here (fake providers for the
    offline path, a real key for a live class), and the vectors either side of that
    switch are not comparable. See the `store` module docstring.
    """
    if str(settings.storage.db_path) == ":memory:":
        return InMemoryVectorStore()
    return ChromaVectorStore(
        settings.storage.chroma_path,
        embedding_model=settings.embedding.model,
        # Both, because both decide the vector space. Switching provider while the
        # model name stays put — which is what a developer does every time they run
        # against the fakes — would otherwise write one width into a collection
        # named for another. See `_collection_name`.
        embedding_provider=settings.embedding.provider,
    )


def build_runtime(settings: Settings) -> AiRuntime:
    return AiRuntime(settings)
