"""The vector store and `VectorRetriever`.

The store tests run against both implementations, for the same reason the step
store's do: tests use the in-memory one and a workshop uses Chroma, so any
behaviour the two disagree on is a bug that ships. In particular, both must report
similarity in the same units — the relevance threshold is expressed in cosine
similarity, and a Chroma distance leaking through would make the threshold mean
one thing in production and another in tests.
"""

from __future__ import annotations

import pytest

from ai_backend.contracts.models import Chunk, Modality
from ai_backend.observability import InMemoryStepStore, trace_context
from ai_backend.observability import trace as trace_module
from ai_backend.providers.fake import FakeEmbeddingProvider
from ai_backend.retrievers.store import (
    ChromaVectorStore,
    InMemoryVectorStore,
    cosine_similarity,
)
from ai_backend.retrievers.vector import VectorRetriever, tokenize

LEAVE = "Parental leave is 16 weeks of fully paid leave after a birth or adoption."
REMOTE = "Remote work is permitted for up to three days each week."
CHEESE = "Alpine cheese is matured in mountain cellars for eighteen months."


@pytest.fixture(params=["memory", "chroma"])
def store(request: pytest.FixtureRequest):
    if request.param == "memory":
        return InMemoryVectorStore()
    # Ephemeral, so nothing touches disk. `embedding_function=None` is set inside
    # ChromaVectorStore — without it Chroma downloads an ONNX model on first use
    # and the offline guarantee breaks.
    return ChromaVectorStore(None)


@pytest.fixture
def traced_store():
    fresh = InMemoryStepStore()
    previous = trace_module.get_store()
    trace_module.configure(store=fresh)
    yield fresh
    trace_module.configure(store=previous)


def _chunk(text: str, *, document_id: str = "d1", location: str = "p. 1") -> Chunk:
    return Chunk(
        document_id=document_id,
        content=text,
        modality=Modality.TEXT,
        source_location=location,
    )


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------


def test_identical_vectors_are_maximally_similar() -> None:
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_orthogonal_vectors_score_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_a_zero_vector_is_similar_to_nothing() -> None:
    """Guards a division by zero, and states the intent.

    Empty or punctuation-only text embeds to zero, and it should match nothing —
    including itself.
    """
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0


def test_mismatched_dimensions_score_zero_rather_than_raising() -> None:
    """A dimension mismatch means the index was built with another model.

    Returning zero degrades to "finds nothing", which surfaces as the visible
    "no relevant content" step; raising would surface as a 500 during a demo.
    """
    assert cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0


# ---------------------------------------------------------------------------
# Switching embedding model against a persisted index
#
# Regression tests for a real 500. `.env` was switched from the fake embedding
# provider (4096 dims) to `text-embedding-3-small` (1536), and an upload against
# the already-populated `var/chroma` died inside Chroma with
# "Collection expecting embedding with dimension of 4096, got 1536" — a stack
# trace in the browser, mid-demo.
#
# These use a persistent client on tmp_path because the bug only exists across
# process restarts; an ephemeral client cannot reproduce it.
# ---------------------------------------------------------------------------


async def test_each_embedding_model_gets_its_own_collection(tmp_path) -> None:
    """Switching model is a non-event, not a crash.

    Vectors from two models are not comparable, so the second model must start
    from an empty index rather than either failing or — worse — appending into the
    first model's collection and silently poisoning similarity.
    """
    first = ChromaVectorStore(tmp_path / "chroma", embedding_model="fake-embedding")
    await first.add(
        session_id="s1", chunks=[_chunk(LEAVE)], vectors=[[0.1] * 8]
    )

    second = ChromaVectorStore(
        tmp_path / "chroma", embedding_model="text-embedding-3-small"
    )
    # A different width, exactly as the real switch was.
    await second.add(session_id="s1", chunks=[_chunk(REMOTE)], vectors=[[0.2] * 4])

    assert await first.count(session_id="s1") == 1
    assert await second.count(session_id="s1") == 1
    assert [c.content for c in await second.all_chunks(session_id="s1")] == [REMOTE]


async def test_switching_provider_under_one_model_name_gets_its_own_collection(
    tmp_path,
) -> None:
    """The case that actually bit, and the one the model-only key could not see.

    Switching *model* was the case the key was designed for, and it works. What
    happens far more often is switching **provider** while the model name stays
    put: running with `AXIS_EMBEDDING__PROVIDER=fake` and leaving
    `AXIS_EMBEDDING__MODEL=text-embedding-3-small` in `.env`, which is the ordinary
    shape of a development run against a real config file.

    The fake's 4096-dimensional vectors then went into the collection named for
    `text-embedding-3-small`, and the next real run met a collection whose name
    promised 1536 and whose contents were 4096. The width check below caught it —
    so this was a narrow gap and not silent corruption — but the error arrived on a
    student's upload in the middle of a demo, which is the wrong place to discover
    that two vector spaces share a name.

    A vector space is a provider *and* a model. Both are in the key now.
    """
    fake = ChromaVectorStore(
        tmp_path / "chroma",
        embedding_model="text-embedding-3-small",
        embedding_provider="fake",
    )
    await fake.add(session_id="s1", chunks=[_chunk(LEAVE)], vectors=[[0.1] * 16])

    real = ChromaVectorStore(
        tmp_path / "chroma",
        embedding_model="text-embedding-3-small",
        embedding_provider="openai",
    )
    # Same model name, different provider, different width. Must be a different
    # collection rather than a refusal — switching to the fakes and back is a thing
    # a developer does several times an hour.
    await real.add(session_id="s1", chunks=[_chunk(REMOTE)], vectors=[[0.2] * 4])

    assert await fake.count(session_id="s1") == 1
    assert await real.count(session_id="s1") == 1
    assert [c.content for c in await real.all_chunks(session_id="s1")] == [REMOTE]


async def test_a_model_keeping_its_name_but_changing_width_is_a_clear_refusal(
    tmp_path,
) -> None:
    """The backstop, for when the collection name cannot tell the two apart.

    OpenAI's `dimensions` parameter, a re-tagged local model, or an index built
    before collections were keyed by model all land here. It must be an
    `IngestionError` — the upload endpoint catches `AxisError` per file and reports
    the reason — and never a raw Chroma exception, which is a 500.
    """
    from ai_backend.errors import IngestionError

    first = ChromaVectorStore(tmp_path / "chroma", embedding_model="same-name")
    await first.add(session_id="s1", chunks=[_chunk(LEAVE)], vectors=[[0.1] * 8])

    reopened = ChromaVectorStore(tmp_path / "chroma", embedding_model="same-name")

    with pytest.raises(IngestionError) as caught:
        await reopened.add(session_id="s1", chunks=[_chunk(REMOTE)], vectors=[[0.2] * 4])

    # The student sees this text, so it has to name the numbers and the fix.
    assert "8" in caught.value.message and "4" in caught.value.message
    assert "delete" in (caught.value.detail or "").lower()


async def test_querying_a_stale_index_is_unavailable_not_a_failed_upload(
    tmp_path,
) -> None:
    """Same condition at query time carries a different meaning.

    Nothing was ingested, so `IngestionError` would be a lie; the honest statement
    is that this index cannot serve this configuration.
    """
    from ai_backend.errors import RetrievalUnavailableError

    built = ChromaVectorStore(tmp_path / "chroma", embedding_model="same-name")
    await built.add(session_id="s1", chunks=[_chunk(LEAVE)], vectors=[[0.1] * 8])

    reopened = ChromaVectorStore(tmp_path / "chroma", embedding_model="same-name")

    with pytest.raises(RetrievalUnavailableError):
        await reopened.search(session_id="s1", vector=[0.2] * 4, top_k=5)


# ---------------------------------------------------------------------------
# Vector store, both implementations
# ---------------------------------------------------------------------------


async def test_a_chunk_round_trips_with_its_metadata(store) -> None:
    chunk = _chunk(LEAVE, location="p. 4")
    embedder = FakeEmbeddingProvider()

    with trace_context(session_id="s1", trace_id="t1"):
        vectors = (await embedder.embed([chunk.content])).vectors
    await store.add(session_id="s1", chunks=[chunk], vectors=vectors)

    found = await store.search(session_id="s1", vector=vectors[0], top_k=5)

    assert len(found) == 1
    assert found[0].id == chunk.id
    assert found[0].document_id == "d1"
    assert found[0].source_location == "p. 4"
    assert found[0].content == LEAVE


async def test_similarity_is_reported_in_the_same_units_by_both_stores(store) -> None:
    """The property that makes one relevance threshold work everywhere.

    Chroma returns a cosine *distance*; the adapter converts it. If that conversion
    were dropped, `min_similarity=0.25` would mean "quite similar" in tests and
    "barely similar" in production.
    """
    chunk = _chunk(LEAVE)
    embedder = FakeEmbeddingProvider()

    with trace_context(session_id="s1", trace_id="t1"):
        vectors = (await embedder.embed([chunk.content])).vectors
    await store.add(session_id="s1", chunks=[chunk], vectors=vectors)

    # Searching with the chunk's own vector must score ~1.0 in both stores.
    found = await store.search(session_id="s1", vector=vectors[0], top_k=1)

    assert found[0].score == pytest.approx(1.0, abs=0.02)


async def test_chunks_are_scoped_by_session(store) -> None:
    """One student must not retrieve another's documents.

    Per-session scoping is the only data isolation Axis has (PRD Section 3).
    """
    embedder = FakeEmbeddingProvider()
    with trace_context(session_id="x", trace_id="t"):
        vectors = (await embedder.embed([LEAVE])).vectors

    await store.add(session_id="mine", chunks=[_chunk(LEAVE)], vectors=vectors)
    await store.add(session_id="theirs", chunks=[_chunk(LEAVE)], vectors=vectors)

    assert await store.count(session_id="mine") == 1
    found = await store.search(session_id="mine", vector=vectors[0], top_k=10)
    assert len(found) == 1


async def test_deleting_a_session_removes_only_its_chunks(store) -> None:
    embedder = FakeEmbeddingProvider()
    with trace_context(session_id="x", trace_id="t"):
        vectors = (await embedder.embed([LEAVE])).vectors
    await store.add(session_id="a", chunks=[_chunk(LEAVE)], vectors=vectors)
    await store.add(session_id="b", chunks=[_chunk(LEAVE)], vectors=vectors)

    await store.delete_session(session_id="a")

    assert await store.count(session_id="a") == 0
    assert await store.count(session_id="b") == 1


async def test_adding_mismatched_chunks_and_vectors_is_refused(store) -> None:
    """Storing a chunk against the wrong vector would corrupt the index silently.

    Every later retrieval would be subtly wrong with nothing to point at, so this
    fails loudly at the boundary instead.
    """
    with pytest.raises(ValueError, match="embedded exactly once"):
        await store.add(session_id="s1", chunks=[_chunk(LEAVE)], vectors=[])


async def test_searching_an_empty_session_returns_nothing(store) -> None:
    found = await store.search(session_id="nobody", vector=[0.1] * 4096, top_k=5)

    assert found == []


# ---------------------------------------------------------------------------
# VectorRetriever
# ---------------------------------------------------------------------------


async def _seeded_retriever(*, hybrid: bool = False, min_similarity: float = 0.25):
    store = InMemoryVectorStore()
    embedder = FakeEmbeddingProvider()
    chunks = [
        _chunk(LEAVE, document_id="handbook", location="Leave"),
        _chunk(REMOTE, document_id="handbook", location="Remote"),
        _chunk(CHEESE, document_id="cheese", location="p. 1"),
    ]
    with trace_context(session_id="s1", trace_id="seed"):
        vectors = (await embedder.embed([c.content for c in chunks])).vectors
    await store.add(session_id="s1", chunks=chunks, vectors=vectors)

    return VectorRetriever(
        store=store,
        embeddings=embedder,
        hybrid=hybrid,
        min_similarity=min_similarity,
    )


async def test_retrieval_finds_the_relevant_chunk(traced_store) -> None:
    retriever = await _seeded_retriever()

    with trace_context(session_id="s1", trace_id="t1"):
        context = await retriever.retrieve(
            "How long is parental leave?", session_id="s1", top_k=3
        )

    assert context.chunks
    assert context.chunks[0].source_location == "Leave"


async def test_an_irrelevant_query_retrieves_nothing_rather_than_raising(
    traced_store,
) -> None:
    """Empty is a result. Section 11 requires it be a *visible step*.

    The retriever must not raise: raising would turn a normal outcome into an
    exception the pipeline has to catch and convert back.
    """
    retriever = await _seeded_retriever()

    with trace_context(session_id="s1", trace_id="t1"):
        context = await retriever.retrieve(
            "What is the position on quantum cryptography?", session_id="s1", top_k=3
        )

    assert context.chunks == []
    assert context.is_empty


async def test_an_empty_retrieval_explains_itself_in_the_trace(traced_store) -> None:
    """"No sufficiently relevant content found" — with the reason.

    A bare "0 results" invites the conclusion that retrieval is broken rather than
    that the documents do not cover the question.
    """
    retriever = await _seeded_retriever()

    with trace_context(session_id="s1", trace_id="t1"):
        await retriever.retrieve("Quantum cryptography policy?", session_id="s1")

    step = next(s for s in traced_store.all_steps if s.step_type.value == "retrieve")
    assert step.attributes["chunks_found"] == 0
    assert "no sufficiently relevant" in (step.raw_output or "").lower()
    # The threshold and the closest score are both stated, so a student can see
    # how near it came.
    assert "threshold" in (step.raw_output or "").lower()
    assert "best_similarity" in step.attributes


async def test_the_trace_records_what_was_retrieved_structurally(traced_store) -> None:
    """The evaluation harness scores retrieval by reading this, not by re-querying."""
    retriever = await _seeded_retriever()

    with trace_context(session_id="s1", trace_id="t1"):
        await retriever.retrieve("parental leave duration", session_id="s1", top_k=2)

    step = next(s for s in traced_store.all_steps if s.step_type.value == "retrieve")
    retrieved = step.attributes["retrieved"]
    assert retrieved
    assert {"chunk_id", "document_id", "source_location", "score"} <= set(retrieved[0])


async def test_retrieval_cost_lands_on_the_retrieve_step(traced_store) -> None:
    """Embedding the query costs money, and it belongs to retrieval.

    Attributing it here is what makes retrieval's cost visible next to
    generation's in the Compare table.
    """
    retriever = await _seeded_retriever()

    with trace_context(session_id="s1", trace_id="t1"):
        context = await retriever.retrieve("parental leave", session_id="s1")

    step = next(s for s in traced_store.all_steps if s.step_type.value == "retrieve")
    assert step.usage.cost_usd > 0
    assert context.usage.cost_usd > 0


async def test_is_ready_reflects_whether_anything_is_indexed(traced_store) -> None:
    """A strategy with no index must report unavailable, not answer emptily."""
    retriever = await _seeded_retriever()

    assert await retriever.is_ready("s1") is True
    assert await retriever.is_ready("never-used") is False


async def test_hybrid_mode_is_reported_in_the_trace(traced_store) -> None:
    """So a student can see which retrieval arms ran."""
    retriever = await _seeded_retriever(hybrid=True)

    with trace_context(session_id="s1", trace_id="t1"):
        await retriever.retrieve("parental leave", session_id="s1")

    step = next(s for s in traced_store.all_steps if s.step_type.value == "retrieve")
    assert step.attributes["mode"] == "hybrid"
    assert "keyword_candidates" in step.attributes


async def test_hybrid_still_returns_nothing_for_an_irrelevant_query(
    traced_store,
) -> None:
    """The regression the golden set caught.

    Fusing before thresholding made hybrid retrieval incapable of returning
    nothing, which silently broke the ungrounded criterion — every query matched
    something. Both arms now gate on relevance before fusion.
    """
    retriever = await _seeded_retriever(hybrid=True)

    with trace_context(session_id="s1", trace_id="t1"):
        context = await retriever.retrieve(
            "What is the position on quantum cryptography?", session_id="s1"
        )

    assert context.chunks == [], (
        "hybrid retrieval must be able to find nothing, or the ungrounded path "
        "can never fire"
    )


async def test_keyword_search_needs_more_than_one_incidental_word(
    traced_store,
) -> None:
    """The keyword arm's relevance floor.

    BM25 will happily match a single shared common word. "leave" appears in the
    handbook, so a question containing it but about something else entirely must
    not surface that chunk on lexical grounds alone.
    """
    retriever = await _seeded_retriever(hybrid=True)

    with trace_context(session_id="s1", trace_id="t1"):
        context = await retriever.retrieve(
            "When did the Roman empire leave Britain entirely?", session_id="s1"
        )

    locations = {c.source_location for c in context.chunks}
    assert "Remote" not in locations, locations


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


def test_tokenize_drops_stopwords_and_punctuation() -> None:
    assert tokenize("What is the parental leave policy?") == [
        "parental",
        "leave",
        "policy",
    ]


def test_tokenize_keeps_numbers_and_identifiers() -> None:
    """A question about "form W-8BEN" is a lexical match, not a semantic one."""
    tokens = tokenize("Which form is W-8BEN, and is 16 weeks correct?")

    assert "w" in tokens and "8ben" in tokens
    assert "16" in tokens
