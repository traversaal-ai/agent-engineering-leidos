"""`VectorRetriever` — Chroma behind the shared `Retriever` interface.

Shared by **two** strategies, not one: Naive RAG uses it single-shot at Milestone
0, and Agentic RAG's ReAct loop calls the same object at Milestone 1 with no
change here. That reuse is the whole point of the interface
(System Design Section 4).

Two things this class must get right, both from the `Retriever` docstring:

- **Empty is a result, not an error.** When nothing clears the relevance
  threshold it returns an empty `RetrievedContext`. Section 11 requires "no
  sufficiently relevant content found" be a *visible trace step*, and raising
  would make it an exception instead — which the pipeline would then have to
  catch and translate back into the thing it already was.
- **The threshold is expressed in cosine similarity**, which both vector stores
  normalise to, so it means the same thing in tests and in production.

Retrieval mode is a constructor flag rather than a subclass, so Section 10's
hybrid decision can be measured against the dense baseline on the same golden set
— the delta being the teaching artifact.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

from ai_backend.contracts.models import Chunk, RetrievedContext, StepType
from ai_backend.contracts.providers import EmbeddingProvider
from ai_backend.observability.trace import atrace_step
from ai_backend.providers.base import vector_preview
from ai_backend.retrievers.store import VectorStore
from ai_backend.textutil import tokenize

# Cosine similarity below which a chunk is treated as irrelevant. Tuned against
# the golden set; see `ai_backend/evaluation/`. Set too high, real answers are
# reported ungrounded; too low, every question retrieves something and the
# "nothing relevant found" path never fires when it should.
DEFAULT_MIN_SIMILARITY = 0.25

# How many candidates each retrieval arm fetches before fusion. Wider than the
# final top_k because fusion can only reorder what it was given, and a chunk that
# only keyword search would have found has to be in the pool to win.
_CANDIDATE_MULTIPLIER = 3

# BM25 constants. k1 damps the effect of repeating a term; b controls how much a
# long chunk is penalised. These are the standard values and are not worth tuning
# at classroom corpus sizes.
_BM25_K1 = 1.5
_BM25_B = 0.75

# The keyword arm's relevance floor: the fraction of a query's distinct terms a
# chunk must contain to count as a match at all.
#
# The dense arm has `min_similarity`; without an equivalent here, BM25 surfaces a
# chunk that shares a single common word. "What is the company's position on
# quantum cryptography?" matched a paragraph containing only the word "company",
# which was enough to make hybrid retrieval never return nothing — and so to break
# the ungrounded criterion entirely. A non-zero score is not the same as a
# relevant match.
#
# 0.4 keeps genuine lexical hits (a question about form W-8BEN shares most of its
# terms with the passage about it) while rejecting incidental single-word overlap.
_MIN_TERM_COVERAGE = 0.4

# Reciprocal rank fusion's damping constant. 60 is the value from the original
# paper and is deliberately large: it flattens the difference between rank 1 and
# rank 2, so a chunk both arms rank moderately well beats one arm's top hit.
_RRF_K = 60

# How many scored candidates reach the trace, and how much of each. Enough to show
# the threshold with kept passages above it and rejected ones below — which needs
# only a handful either side. `top_k * _CANDIDATE_MULTIPLIER` is 15 by default, so
# this is usually the whole candidate pool anyway.
MAX_CANDIDATES_SHOWN = 12
_CANDIDATE_PREVIEW_CHARS = 180


class VectorRetriever:
    """Dense (and optionally hybrid) retrieval over the session's chunks."""

    name = "vector"

    def __init__(
        self,
        *,
        store: VectorStore,
        embeddings: EmbeddingProvider,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
        hybrid: bool = False,
    ) -> None:
        self._store = store
        self._embeddings = embeddings
        self._min_similarity = min_similarity
        self._hybrid = hybrid

    @property
    def mode(self) -> str:
        """Reported into the trace, so a student can see which arm(s) ran."""
        return "hybrid" if self._hybrid else "dense"

    async def retrieve(
        self, query: str, *, session_id: str, top_k: int = 5
    ) -> RetrievedContext:
        # `atrace_step` rather than the `@traced` decorator, because this step's
        # attributes are the interesting part: how many candidates each arm
        # returned, how many survived the threshold, and the best score. A
        # decorator can only record arguments and a return value, and "retrieval
        # found nothing" then looks identical to "retrieval was never asked" —
        # which is exactly the distinction Section 11 requires be visible.
        async with atrace_step(
            StepType.RETRIEVE,
            label="VectorRetriever.retrieve",
            raw_input=query,
            attributes={"mode": self.mode, "top_k": top_k},
        ) as step:
            embedded = await self._embeddings.embed([query])
            step.add_usage(embedded.usage)
            if not embedded.vectors:
                step.set_attribute("chunks_found", 0)
                step.set_output("The embedding provider returned no vector.")
                return RetrievedContext(usage=embedded.usage)

            # The query's own vector, recorded on the step that used it.
            #
            # `purpose: "query"` mirrors what the ingestion stage records for the
            # indexing side, and the pairing is the point: the same model turned a
            # document into these numbers and has now turned a question into
            # numbers of the same width. Similarity search is only meaningful
            # because both live in one space, and a student who has not seen the
            # two side by side has no reason to believe that.
            step.set_attribute("query_vector", {
                "purpose": "query",
                "model": self._embeddings.model,
                "text": query,
                **vector_preview(embedded.vectors[0]),
            })

            candidates = max(top_k, top_k * _CANDIDATE_MULTIPLIER)
            dense = await self._store.search(
                session_id=session_id, vector=embedded.vectors[0], top_k=candidates
            )
            step.set_attribute("dense_candidates", len(dense))
            best = max((c.score or 0.0 for c in dense), default=0.0)

            # Each arm applies its own relevance gate *before* fusion, and that
            # ordering is not incidental. An earlier version fused first and
            # thresholded never, on the reasoning that a rank-derived score cannot
            # be compared against a cosine threshold. True, but the consequence
            # was that hybrid retrieval could never return nothing: every query
            # matched something, so the "no sufficiently relevant content found"
            # path stopped firing and the ungrounded criterion silently broke.
            # The golden set caught it — 0 of 4 unanswerable questions handled —
            # because the acceptance tests run dense-only by default.
            #
            # Gating per arm keeps both properties: fusion still only compares
            # ranks within an arm, and a chunk neither arm considered relevant
            # never enters the pool.
            relevant_dense = [c for c in dense if (c.score or 0.0) >= self._min_similarity]

            # Every candidate that was *considered*, kept or not, with its score.
            #
            # The single most explanatory thing this platform can put on a screen.
            # Retrieval used to render as "3 passages · best 0.81", which states an
            # outcome and hides the mechanism: a student cannot tell that the system
            # scored twenty passages, ranked them, and drew a line. Showing the
            # rejected ones next to the kept ones — with the threshold visible
            # between them — is what turns "it found the right passage" from an
            # assertion into something they can check, and it is also the only way
            # the "nothing relevant found" path stops looking like a bug.
            step.set_attribute("threshold", self._min_similarity)
            step.set_attribute(
                "candidates",
                [
                    {
                        "location": c.source_location or "unknown location",
                        "document_id": c.document_id,
                        "score": round(c.score or 0.0, 4),
                        "kept": (c.score or 0.0) >= self._min_similarity,
                        "preview": c.content[:_CANDIDATE_PREVIEW_CHARS],
                    }
                    for c in dense[:MAX_CANDIDATES_SHOWN]
                ],
            )

            if self._hybrid:
                corpus = await self._store.all_chunks(session_id=session_id)
                # `_bm25_rank` already drops zero-scoring chunks, so a chunk
                # containing none of the query's terms is absent by construction.
                keyword = _bm25_rank(query, corpus, top_k=candidates)
                step.set_attribute("keyword_candidates", len(keyword))
                ranked = _reciprocal_rank_fusion(relevant_dense, keyword)
            else:
                ranked = relevant_dense

            chunks = ranked[:top_k]
            step.set_attribute("chunks_found", len(chunks))
            step.set_attribute("best_similarity", round(best, 4))
            # Structured alongside the human-readable output below, because the
            # evaluation harness scores retrieval by reading the trace rather than
            # by re-querying (see `evaluation/runner.py`). Parsing the prose would
            # couple the scorer to this module's phrasing; a list of ids does not.
            step.set_attribute(
                "retrieved",
                [
                    {
                        "chunk_id": c.id,
                        "document_id": c.document_id,
                        "source_location": c.source_location,
                        "score": round(c.score or 0.0, 4),
                    }
                    for c in chunks
                ],
            )

            if not chunks:
                # Worded so it appears verbatim in the trace a student reads, and
                # says *why* — a bare "0 results" invites the conclusion that
                # retrieval is broken rather than that the documents do not cover
                # the question.
                step.set_output(
                    f"No sufficiently relevant content found. Searched "
                    f"{len(dense)} candidates; the closest scored "
                    f"{best:.3f}, below the {self._min_similarity} threshold."
                )
            else:
                step.set_output(
                    "\n".join(
                        f"[{i}] {c.source_location} (similarity {c.score:.3f})"
                        for i, c in enumerate(chunks, start=1)
                    )
                )

            return RetrievedContext(
                chunks=chunks,
                # The embedding call is the only cost here; the search itself is
                # local. Attributing it to this step is what makes retrieval's
                # cost visible next to generation's.
                usage=embedded.usage,
            )

    async def is_ready(self, session_id: str) -> bool:
        return await self._store.count(session_id=session_id) > 0


def _bm25_rank(query: str, corpus: Sequence[Chunk], *, top_k: int) -> list[Chunk]:
    """Classic BM25 over the session's chunks.

    The keyword half of Section 10's hybrid retrieval, and it earns its place on
    the cases dense embeddings are worst at: exact identifiers, product codes,
    proper nouns, and any term that was rare in the embedding model's training
    data. A question about "form W-8BEN" is a lexical match, not a semantic one.
    """
    terms = tokenize(query)
    if not terms or not corpus:
        return []

    tokenized = [tokenize(c.content) for c in corpus]
    lengths = [len(t) for t in tokenized]
    average_length = sum(lengths) / len(lengths) if lengths else 0.0
    if average_length == 0:
        return []

    # In how many chunks does each term appear at all.
    document_frequency = Counter()
    for tokens in tokenized:
        for term in set(terms) & set(tokens):
            document_frequency[term] += 1

    total = len(corpus)
    distinct_terms = set(terms)
    scored: list[Chunk] = []
    for chunk, tokens, length in zip(corpus, tokenized, lengths, strict=True):
        counts = Counter(tokens)

        # The relevance floor, applied before scoring: a chunk sharing one
        # incidental word with the query is not a keyword hit. See
        # `_MIN_TERM_COVERAGE`.
        matched = distinct_terms & set(tokens)
        if len(matched) / len(distinct_terms) < _MIN_TERM_COVERAGE:
            continue

        score = 0.0
        for term in terms:
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            appearances = document_frequency[term]
            # Inverse document frequency, smoothed. A term in every chunk scores
            # ~0: it cannot discriminate between them.
            idf = math.log(1 + (total - appearances + 0.5) / (appearances + 0.5))
            denominator = frequency + _BM25_K1 * (
                1 - _BM25_B + _BM25_B * length / average_length
            )
            score += idf * (frequency * (_BM25_K1 + 1)) / denominator
        if score > 0:
            scored.append(chunk.model_copy(update={"score": score}))

    scored.sort(key=lambda c: c.score or 0.0, reverse=True)
    return scored[:top_k]


def _reciprocal_rank_fusion(dense: list[Chunk], keyword: list[Chunk]) -> list[Chunk]:
    """Merge two ranked lists by rank, not by score.

    The key property: BM25 scores are unbounded and cosine similarities live in
    0..1, so they cannot be added, averaged, or thresholded together — any
    weighting would be arbitrary and would silently shift as corpus size changed
    the BM25 scale. RRF only reads *positions*, so it needs no calibration between
    the two arms.

    A chunk appearing in both lists accumulates from both, which is why fusion
    favours consensus over either arm's confident outlier.

    The fused score is a rank-derived quantity, not a similarity, so it cannot
    be compared against a relevance threshold. Both input lists are therefore
    expected to be *already* relevance-filtered by their own arm — see the note
    at the call site for what went wrong when they were not.
    """
    contributions: dict[str, float] = {}
    seen: dict[str, Chunk] = {}

    for ranking in (dense, keyword):
        for position, chunk in enumerate(ranking, start=1):
            contributions[chunk.id] = contributions.get(chunk.id, 0.0) + 1.0 / (
                _RRF_K + position
            )
            seen.setdefault(chunk.id, chunk)

    fused = [
        seen[chunk_id].model_copy(update={"score": score})
        for chunk_id, score in contributions.items()
    ]
    fused.sort(key=lambda c: c.score or 0.0, reverse=True)
    return fused


__all__ = ["DEFAULT_MIN_SIMILARITY", "VectorRetriever", "tokenize"]
