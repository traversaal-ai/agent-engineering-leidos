"""The semantic cache — answering a reworded repeat without entering the pipeline.

chapter 07's third pillar, and the one whose teaching value is cheapest: a student
asks a question, asks it again in different words, and watches four LLM calls become
one embedding. The efficiency lesson is a stopwatch rather than an argument.

**No FAISS.** The reference builds a brute-force `IndexFlatL2` over what is, in a
teaching session, a few dozen vectors — so the index buys nothing here, and a
dependency standing between a student and six lines of dot product would be a worse
artefact than the six lines.
`ai_backend/retrievers/store.py::cosine_similarity` already exists.

Three of the reference implementation's flaws are fixed rather than ported, and each
is worth a minute in class because each is a bug that survives testing:

* **It grows without bound and rewrites its whole JSON file on every insert.** Here
  it is a bounded LRU held in memory per session. A workshop is hours long; the file
  was never the point.
* **It reports `1.0 - squared_L2` and calls it similarity.** That number is shown to
  students, so it has to be the number it is called. This computes cosine and states
  the threshold it is compared against.
* **It stores only the answer string**, so a hit has no provenance. PRD Section 6
  requires every answer to carry a citation; an answer whose citations were thrown
  away cannot satisfy that, and "it was cached" is not an exemption. The whole
  `Answer` is stored.

**What is deliberately kept crude: the staleness gate.** `is_time_sensitive` is a
substring match against ~40 keywords, and it is over-eager on purpose — see below.

**Offline, this demonstrates the mechanism and not the selling point.** Measured
against `FakeEmbeddingProvider`, which is a hashed bag of words:

    "When is payment due on a correct invoice?"      1.000  hit
    "when is payment due on a correct invoice"       1.000  hit
    "When is payment due for a correct invoice?"     1.000  hit
    "What is SOW-003's not-to-exceed value?"         0.913  miss
    "How soon must a correct invoice be paid?"       0.447  miss

So a repeat, a punctuation change and a stopword swap all hit, and a genuine
paraphrase does not — because a bag of words has no way to know that "how soon must
it be paid" and "when is payment due" mean the same thing. That is the whole point
of a *semantic* cache, and it needs real embeddings:

    AXIS_EMBEDDING__PROVIDER=openai

The same boundary System Design Section 12 already records for answer content and
for agentic retrieval quality. Worth saying in class rather than discovering live:
demonstrate the cache on a real provider, or demonstrate it offline by re-asking the
same question and being explicit that a paraphrase would need one.
"""

from __future__ import annotations

from collections import OrderedDict

from pydantic import BaseModel

from ai_backend.contracts.models import Answer, StepType
from ai_backend.contracts.providers import EmbeddingProvider
from ai_backend.observability.trace import atrace_step
from ai_backend.retrievers.store import cosine_similarity

# Cosine, not squared-L2. chapter 07 uses an L2 threshold of 0.2 on normalised
# vectors, which is cosine ≥ 0.90; this is a little stricter, because a wrong hit is
# far worse than a miss. A miss costs a query; a hit on a question that only looked
# similar answers something the student did not ask.
DEFAULT_MIN_SIMILARITY = 0.92

# Bounded, unlike the reference. Sized for a teaching session rather than tuned:
# large enough that a class can revisit anything it asked, small enough that a
# runaway loop cannot grow it without limit.
DEFAULT_MAX_ENTRIES = 64

# Questions whose right answer depends on when they are asked. Ported verbatim in
# spirit from `reference/chapter_07_enterprise_rag/semantic_cache.py`.
#
# **Deliberately over-eager, and it says so on the card.** Substring matching means
# "this year" also fires inside "in this yearbook", and that is the right way for
# this to be wrong: a false positive costs one uncached query, a false negative
# answers a question about today with last week's answer. A cache with no staleness
# policy is the version of this feature that teaches the wrong lesson, and a crude
# gate a student can read in ten seconds teaches it better than a subtle one.
TIME_SENSITIVE_KEYWORDS = (
    "today", "tonight", "now", "currently", "current",
    "latest", "recent", "recently", "right now",
    "at the moment", "at present", "as of now",
    "this week", "this month", "this year",
    "this quarter", "this season", "this morning",
    "this afternoon", "this evening", "this weekend",
    "yesterday", "tomorrow", "last week", "last month",
    "last year", "upcoming", "live", "breaking",
    "just happened", "what time", "what day", "what date",
    "happening now", "events today", "news today",
    "news this week", "stock price", "share price",
    "weather", "forecast", "temperature",
    "real-time", "realtime", "schedule today",
    "outage", "down right now",
)


def is_time_sensitive(question: str) -> bool:
    """Whether this question's answer goes stale, so the cache must not touch it."""
    lowered = question.lower()
    return any(keyword in lowered for keyword in TIME_SENSITIVE_KEYWORDS)


class CacheHit(BaseModel):
    """A stored answer, and the evidence for serving it."""

    answer: Answer
    similarity: float
    matched_question: str


class _Entry(BaseModel):
    question: str
    embedding: list[float]
    answer: Answer


class SemanticCache:
    """Per-corpus store of answered questions, keyed by embedding proximity.

    **Scoped to a session *and* a corpus, and that is a correctness boundary rather
    than a tidiness one.** A cached answer carries the citations of the documents it
    was drawn from. Sharing one across sessions would hand a student an answer about
    somebody else's uploads; sharing one across corpora would answer a question about
    their own documents with a passage from the demo set — same failure, one level
    down, and the one that only appeared once a session could hold two corpora.

    Not persisted. A restart loses it, which for a workshop is the right trade — the
    alternative is a stale answer surviving into a session whose index is different.
    """

    def __init__(
        self,
        *,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._min_similarity = min_similarity
        self._max_entries = max_entries
        # `OrderedDict` keyed by **index scope** — a session *and* a corpus — each
        # holding an LRU of entries keyed by the question text, so asking the
        # identical question twice replaces its entry rather than storing it twice.
        #
        # Scope rather than session, because a cached answer is an answer about a
        # particular corpus. Keying on the session alone would serve a demo-corpus
        # answer to a question asked against a student's own documents, with
        # citations pointing at files they never uploaded. Keying on the scope makes
        # switching correct by construction — no invalidation to remember — and lets
        # a student switch back and still find their earlier answers.
        self._by_scope: OrderedDict[str, OrderedDict[str, _Entry]] = OrderedDict()

    @property
    def min_similarity(self) -> float:
        return self._min_similarity

    def size(self, scope: str) -> int:
        return len(self._by_scope.get(scope, ()))

    async def lookup(
        self,
        question: str,
        *,
        scope: str,
        embeddings: EmbeddingProvider,
        enabled: bool = True,
        keyed_on: str = "raw",
    ) -> CacheHit | None:
        """Look for an answer to a question close enough to this one.

        Emits its step either way, so the canvas can draw a miss. `keyed_on` is
        recorded rather than decided here: the pipeline knows whether it is looking
        up the question as typed or its resolved form, and which one it used is a
        thing a student needs to see — a cache keyed on "How long is it?" would
        serve a previous *it*.
        """
        async with atrace_step(
            StepType.CACHE_LOOKUP,
            label="SemanticCache.lookup",
            raw_input=question,
        ) as step:
            step.set_attribute("threshold", self._min_similarity)
            step.set_attribute("entries", self.size(scope))
            step.set_attribute("keyed_on", keyed_on)

            if not enabled:
                step.set_attribute("hit", False)
                step.set_attribute("skipped_reason", "disabled")
                step.set_output("the cache is turned off for this query")
                return None

            if is_time_sensitive(question):
                step.set_attribute("hit", False)
                step.set_attribute("skipped_reason", "time_sensitive")
                step.set_output(
                    "not cached: this question's answer depends on when it is asked, "
                    "so a stored one could be out of date"
                )
                return None

            entries = self._by_scope.get(scope)
            if not entries:
                step.set_attribute("hit", False)
                step.set_attribute("skipped_reason", "empty")
                step.set_output("nothing cached for this session yet")
                return None

            embedded = await embeddings.embed([question])
            step.add_usage(embedded.usage)
            if not embedded.vectors:
                step.set_attribute("hit", False)
                step.set_attribute("skipped_reason", "no_embedding")
                step.set_output("the question could not be embedded, so nothing was compared")
                return None

            vector = embedded.vectors[0]
            best_key, best_score = "", -1.0
            for key, entry in entries.items():
                score = cosine_similarity(vector, entry.embedding)
                if score > best_score:
                    best_key, best_score = key, score

            step.set_attribute("similarity", round(best_score, 4))
            step.set_attribute("closest_question", entries[best_key].question)

            if best_score < self._min_similarity:
                step.set_attribute("hit", False)
                step.set_output(
                    f"miss: the closest stored question scored {best_score:.3f}, "
                    f"below the {self._min_similarity} threshold"
                )
                return None

            entry = entries[best_key]
            # LRU: a hit is a use, so it moves to the end and survives eviction.
            entries.move_to_end(best_key)

            step.set_attribute("hit", True)
            step.set_attribute("matched_question", entry.question)
            step.set_attribute("citations", len(entry.answer.citations))
            step.set_output(
                f"hit at {best_score:.3f}: answering with the stored answer to "
                f"{entry.question!r}. No further LLM call was made."
            )
            return CacheHit(
                answer=entry.answer,
                similarity=best_score,
                matched_question=entry.question,
            )

    async def store(
        self,
        question: str,
        answer: Answer,
        *,
        scope: str,
        embeddings: EmbeddingProvider,
    ) -> None:
        """Remember this answer, unless the question should never be cached.

        Not traced. Every other external call in Axis is, and the exception is
        deliberate: this runs *after* the answer has been returned, so a step here
        would appear in the trace below `synthesize` and read as part of producing
        the answer. Its cost — one embedding — is real and is charged to the
        session; what it is not is part of the run a student is watching.
        """
        if is_time_sensitive(question):
            return
        if not answer.grounded:
            # An ungrounded answer is "I could not find that", and caching it would
            # make a refusal permanent for every rewording of the question — long
            # after the document that answers it has been uploaded.
            return

        embedded = await embeddings.embed([question])
        if not embedded.vectors:
            return

        entries = self._by_scope.setdefault(scope, OrderedDict())
        entries[question] = _Entry(
            question=question, embedding=embedded.vectors[0], answer=answer
        )
        entries.move_to_end(question)
        while len(entries) > self._max_entries:
            entries.popitem(last=False)

        # Bound the number of *scopes* too. A long-running server would otherwise
        # keep every session's answers for as long as the process lives.
        self._by_scope.move_to_end(scope)
        while len(self._by_scope) > self._max_entries:
            self._by_scope.popitem(last=False)

    def invalidate(self, scope: str) -> int:
        """Forget one corpus's answers. Returns how many were dropped.

        **Called on every successful ingest**, and that is not housekeeping. A
        cached answer is an answer *about a particular corpus*: once another
        document is indexed, "what does the contract say about payment" may have a
        different right answer, and serving the old one would be the cache actively
        making the system wrong.

        Note this is *not* needed when switching corpora — entries are keyed by
        scope, so the other corpus's answers were never reachable in the first place.
        """
        dropped = self._by_scope.pop(scope, None)
        return len(dropped) if dropped else 0

    def invalidate_session(self, session_id: str) -> int:
        """Forget every corpus this session holds. Returns how many were dropped.

        For discarding a session, where "which corpora did it have" is not worth
        asking — a prefix sweep is exact and cheap at classroom scale.
        """
        prefix = f"{session_id}::"
        scopes = [s for s in self._by_scope if s == session_id or s.startswith(prefix)]
        return sum(len(self._by_scope.pop(s, ())) for s in scopes)

    def clear(self) -> None:
        self._by_scope.clear()


__all__ = [
    "CacheHit",
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_MIN_SIMILARITY",
    "SemanticCache",
    "TIME_SENSITIVE_KEYWORDS",
    "is_time_sensitive",
]
