"""One suite, every `Retriever`.

**This file is the `Retriever` contract.** The protocol in `contracts/retriever.py`
declares two method signatures; everything that actually constrains a retriever's
behaviour is asserted here, and the docstrings there point back to these tests by name.
That is why the protocol survives having a single implementation: it is a boundary with
an enforced specification, not an indirection.

Only `VectorRetriever` exists, and none is planned — graph retrieval is a non-goal (PRD
Section 3). The suite is still parametrized over a list of factories, because two test
doubles elsewhere implement this protocol and any future implementation should inherit
these tests rather than restate them.

The contract being pinned down:

1. `retrieve` returns a `RetrievedContext`, never raises for "found nothing".
2. Chunks carry a `document_id` and a human-meaningful `source_location`, because
   those two fields are what a citation is made of.
3. Retrieval is scoped to its session.
4. `is_ready` distinguishes "no index" from "index with no matches".
5. Retrieval emits exactly one `retrieve` step per call, carrying its own cost.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from ai_backend.contracts.models import Chunk, Modality, RetrievedContext
from ai_backend.contracts.retriever import Retriever
from ai_backend.observability import InMemoryStepStore, trace_context
from ai_backend.observability import trace as trace_module
from ai_backend.providers.fake import FakeEmbeddingProvider
from ai_backend.retrievers.store import InMemoryVectorStore
from ai_backend.retrievers.vector import VectorRetriever

CORPUS = [
    ("handbook", "Leave", "Parental leave is 16 weeks of fully paid parental leave."),
    ("handbook", "Remote", "Remote work is permitted up to three days each week."),
    ("security", "Encryption", "Full-disk encryption is mandatory on every laptop."),
]

RELEVANT_QUERY = "How long is parental leave?"
IRRELEVANT_QUERY = "What is the position on quantum cryptography?"


@pytest.fixture
def traced():
    store = InMemoryStepStore()
    previous = trace_module.get_store()
    trace_module.configure(store=store)
    yield store
    trace_module.configure(store=previous)


async def _build_vector_retriever(session_id: str) -> Retriever:
    store = InMemoryVectorStore()
    embedder = FakeEmbeddingProvider()
    chunks = [
        Chunk(
            document_id=document,
            content=text,
            modality=Modality.TEXT,
            source_location=location,
        )
        for document, location, text in CORPUS
    ]
    with trace_context(session_id=session_id, trace_id="seed"):
        vectors = (await embedder.embed([c.content for c in chunks])).vectors
    await store.add(session_id=session_id, chunks=chunks, vectors=vectors)
    return VectorRetriever(store=store, embeddings=embedder)


# Each entry is a factory taking a session id and returning a seeded retriever. Any
# further implementation is added here and inherits every test below.
RETRIEVERS: list[tuple[str, Callable]] = [("vector", _build_vector_retriever)]


@pytest.fixture(params=[name for name, _ in RETRIEVERS], ids=[n for n, _ in RETRIEVERS])
def factory(request: pytest.FixtureRequest):
    return dict(RETRIEVERS)[request.param]


async def test_returns_a_retrieved_context(factory, traced) -> None:
    retriever = await factory("s1")

    with trace_context(session_id="s1", trace_id="t1"):
        result = await retriever.retrieve(RELEVANT_QUERY, session_id="s1", top_k=3)

    assert isinstance(result, RetrievedContext)


async def test_finds_relevant_content(factory, traced) -> None:
    retriever = await factory("s1")

    with trace_context(session_id="s1", trace_id="t1"):
        result = await retriever.retrieve(RELEVANT_QUERY, session_id="s1", top_k=3)

    assert result.chunks, "a relevant query returned nothing"


async def test_finding_nothing_is_a_result_not_an_exception(factory, traced) -> None:
    """The single most important line of the `Retriever` docstring.

    Section 11 requires "no sufficiently relevant content found" be a visible
    trace step. An implementation that raised would force every caller to catch
    and convert it back into the thing it already was.
    """
    retriever = await factory("s1")

    with trace_context(session_id="s1", trace_id="t1"):
        result = await retriever.retrieve(IRRELEVANT_QUERY, session_id="s1", top_k=3)

    assert result.chunks == []
    assert result.is_empty


async def test_every_chunk_can_be_cited(factory, traced) -> None:
    """A chunk without a document id and a location cannot become a citation.

    PRD Section 6 requires a citation link "back to a specific uploaded document",
    so a retriever returning text with no provenance makes that criterion
    unsatisfiable no matter how good the retrieval is.
    """
    retriever = await factory("s1")

    with trace_context(session_id="s1", trace_id="t1"):
        result = await retriever.retrieve(RELEVANT_QUERY, session_id="s1", top_k=3)

    for chunk in result.chunks:
        assert chunk.document_id, "a chunk with no document cannot be cited"
        assert chunk.source_location, "a chunk with no location cannot be checked"
        assert chunk.content


async def test_respects_top_k(factory, traced) -> None:
    retriever = await factory("s1")

    with trace_context(session_id="s1", trace_id="t1"):
        result = await retriever.retrieve("leave remote encryption", session_id="s1", top_k=1)

    assert len(result.chunks) <= 1


async def test_results_are_ordered_best_first(factory, traced) -> None:
    """The pipeline numbers passages in this order and the model cites by number,
    so an unordered result would scramble which citation means what.
    """
    retriever = await factory("s1")

    with trace_context(session_id="s1", trace_id="t1"):
        result = await retriever.retrieve("parental leave weeks", session_id="s1", top_k=3)

    scores = [c.score or 0.0 for c in result.chunks]
    assert scores == sorted(scores, reverse=True), scores


async def test_retrieval_is_scoped_to_its_session(factory, traced) -> None:
    retriever = await factory("mine")

    with trace_context(session_id="theirs", trace_id="t1"):
        result = await retriever.retrieve(RELEVANT_QUERY, session_id="theirs", top_k=3)

    assert result.chunks == [], "another session's content was retrievable"


async def test_is_ready_distinguishes_no_index_from_no_match(factory, traced) -> None:
    """Two different situations that must not be conflated.

    "This strategy has no index" is a Section 11 failure mode — the strategy
    reports unavailable. "The index has nothing matching" is a normal answer. A
    retriever that returned False for both would make an indexed session look
    broken whenever a question missed.
    """
    retriever = await factory("s1")

    assert await retriever.is_ready("s1") is True
    assert await retriever.is_ready("never-ingested") is False


async def test_emits_exactly_one_retrieve_step_carrying_its_cost(factory, traced) -> None:
    """Uniform instrumentation is what makes the two strategies comparable.

    One step per call, with the embedding cost on it. A retriever that emitted
    none would appear free and would win every cost comparison.
    """
    retriever = await factory("s1")

    with trace_context(session_id="s1", trace_id="t1"):
        await retriever.retrieve(RELEVANT_QUERY, session_id="s1", top_k=3)

    steps = [s for s in traced.all_steps if s.step_type.value == "retrieve"]
    assert len(steps) == 1, [s.label for s in traced.all_steps]
    assert steps[0].usage.cost_usd > 0
    assert steps[0].attributes["chunks_found"] >= 0


async def test_conforms_to_the_retriever_protocol(factory, traced) -> None:
    retriever = await factory("s1")

    assert isinstance(retriever, Retriever)
    assert retriever.name
