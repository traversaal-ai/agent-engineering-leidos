"""Deterministic scoring for retrieval and answers.

**Deterministic, not LLM-as-judge, and that is a decision rather than a shortcut.**
System Design Section 12 allows either. PRD Section 7 flags LLM-as-judge as
biased toward verbose answers, and CLAUDE.md makes this score the gate on starting
the next milestone. A gate that costs money on every run, needs an API key in CI,
and returns a different number each time is not a gate — it is a suggestion. So
Milestone 0 measures what can be measured exactly, and LLM-as-judge arrives at
Milestone 4 where comparing the two strategies' answer *quality* genuinely needs it,
and where a reproducible baseline exists to measure its bias against.

What each metric is for:

- **precision@k** — of the chunks retrieved, how many came from a document the
  question was supposed to need. The standard vector-retrieval metric.
- **recall of expected documents** — did retrieval reach *every* document the
  answer needs. This is the one compound and multi-hop questions fail on a single
  pass, and the number decomposition and the hop loop exist to improve.
- **citation accuracy** — do the cited documents match the expected ones. Catches
  the specific failure of citing something real but irrelevant.
- **content coverage** — does the answer contain the substrings a correct answer
  must contain. Crude, and honest about being crude: it cannot recognise a correct
  paraphrase, so it is a floor rather than a grade.
- **groundedness agreement** — did the system claim grounding exactly when it
  should have. The most important of the five, because both errors are severe: a
  fabricated citation, or a refusal to answer something the documents cover.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ai_backend.contracts.models import Answer, RetrievedContext
from ai_backend.evaluation.golden import GoldenQuestion


class RetrievalScore(BaseModel):
    question_id: str
    retrieved: int = 0
    precision_at_k: float = 0.0
    document_recall: float = 0.0
    # For an unanswerable question the correct retrieval is *nothing*, so
    # precision is undefined and this flag carries the verdict instead.
    correctly_empty: bool | None = None
    # How much of the expected documents was actually read, in chunks.
    #
    # **A different measure from `document_recall`, and the reason it had to
    # exist.** Recall asks "did a chunk from the right document come back", which
    # a single chunk of five satisfies perfectly — so it is structurally blind to
    # the first pain point of naive RAG: *"retrieval returns chunks, not the whole
    # picture."* A question asking for an overview of a corpus can score recall
    # 1.00 having read a fifth of it, and nothing in the report would say so.
    #
    # Populated only for questions declaring `expect_full_coverage`, since for a
    # question about one passage reading the whole document is not better.
    chunks_read: int = 0
    chunks_available: int = 0
    # How many of the question's required facts the retrieved passages actually
    # contain, of how many it declares.
    #
    # **The third measure, and it exists for the same reason the second one does.**
    # `coverage` was added because recall is blind to *how much* of a document came
    # back; this is added because recall is blind to *which part*. Every compound
    # question in the set names exactly two documents, so `document_recall` is a
    # three-valued metric that one chunk per document scores 1.00 on — and under a
    # real embedding model a single blended query does reach both files, while
    # reaching only one of the two figures the question is comparing. The measure
    # said decomposition bought nothing; what it meant was that it could not see.
    #
    # Populated only for questions declaring `expect_passages`, and 0/0 elsewhere:
    # for a question about one fact in one place, "did both facts come back" is not
    # a question.
    facts_found: int = 0
    facts_required: int = 0

    @property
    def coverage(self) -> float:
        """Fraction of the expected documents' chunks that retrieval reached."""
        if not self.chunks_available:
            return 0.0
        return min(1.0, self.chunks_read / self.chunks_available)

    @property
    def fact_recall(self) -> float:
        """Fraction of the required facts the retrieved passages contain."""
        if not self.facts_required:
            return 0.0
        return self.facts_found / self.facts_required


class AnswerScore(BaseModel):
    question_id: str
    grounded_as_expected: bool = False
    citation_accuracy: float = 0.0
    content_coverage: float = 0.0
    # The cited document is not one the question needs. Note this is *not*
    # "fabricated": `NaiveRagPipeline` already drops a citation marker pointing
    # outside the retrieved range, so a surviving citation always names a real
    # retrieved chunk. This flag therefore reports a retrieval precision problem —
    # the model faithfully cited what it was handed, and it was the wrong thing.
    cited_unexpected_document: bool = False
    cost_usd: float = 0.0
    latency_ms: int = 0


class QuestionResult(BaseModel):
    question: GoldenQuestion
    retrieval: RetrievalScore
    answer: AnswerScore
    error: str | None = None

    @property
    def retrieval_passed(self) -> bool:
        """Did retrieval do its job — independent of what the model then said.

        Separated from `passed` because these two are measurable under different
        conditions. Retrieval is fully real under the fake providers: a real
        chunker, a real index, a real similarity search. Answer content is not —
        a fake LLM cannot produce "16 weeks", so a combined verdict would report
        the retriever as broken whenever the harness runs offline.
        """
        if self.error:
            return False
        if self.question.is_unanswerable:
            # The right amount retrieved for an unanswerable question is none.
            return self.retrieval.correctly_empty is True
        return self.retrieval.document_recall >= 1.0

    @property
    def answer_passed(self) -> bool:
        """Did the answer say the right thing.

        Requires a real LLM to be meaningful — see `retrieval_passed`. Reported
        always, gated only on a real-provider run.
        """
        if self.error:
            return False
        if not self.answer.grounded_as_expected:
            return False
        if self.question.is_unanswerable:
            return True
        return self.answer.content_coverage >= 1.0

    @property
    def passed(self) -> bool:
        return self.retrieval_passed and self.answer_passed


def score_retrieval(
    question: GoldenQuestion,
    context: RetrievedContext,
    *,
    document_names: dict[str, str],
    chunk_totals: dict[str, int] | None = None,
) -> RetrievalScore:
    """`document_names` maps document_id → fixture name, so scores can talk in
    the names the golden set uses rather than in opaque ids.

    `chunk_totals` maps fixture name → how many chunks it became, and is used only
    for questions declaring `expect_full_coverage`. Optional because most callers
    have no reason to enumerate the index, and a question about one passage has no
    use for the measure — see `RetrievalScore.chunks_available`.
    """
    retrieved_names = [
        document_names.get(chunk.document_id, "?") for chunk in context.chunks
    ]

    if question.is_unanswerable:
        return RetrievalScore(
            question_id=question.id,
            retrieved=len(context.chunks),
            correctly_empty=not context.chunks,
        )

    expected = set(question.expect_documents)

    coverage: dict[str, int] = {}
    if question.expect_full_coverage and chunk_totals:
        # Chunks *of the expected documents* that came back, against every chunk
        # those documents hold. Chunks from elsewhere are a precision problem and
        # are already counted as one; including them here would let a wide, wrong
        # retrieval report good coverage.
        coverage = {
            "chunks_read": sum(1 for name in retrieved_names if name in expected),
            "chunks_available": sum(
                chunk_totals.get(name, 0) for name in question.expect_documents
            ),
        }

    # Which of the required facts the retrieved *text* carries. Searched across the
    # whole retrieved set rather than per chunk: a fact is found if it came back, and
    # which passage carried it is not what this measures.
    #
    # Counted even when nothing was retrieved, so a run that found no passages scores
    # 0 of 2 rather than 0 of 0 — the second reads as "this question asked for
    # nothing", which is a different and much friendlier claim than the truth.
    facts: dict[str, int] = {}
    if question.expect_passages:
        haystack = "\n".join(chunk.content for chunk in context.chunks)
        facts = {
            "facts_found": sum(1 for f in question.expect_passages if f in haystack),
            "facts_required": len(question.expect_passages),
        }

    if not retrieved_names:
        return RetrievalScore(question_id=question.id, retrieved=0, **coverage, **facts)

    hits = sum(1 for name in retrieved_names if name in expected)
    found = expected & set(retrieved_names)

    return RetrievalScore(
        question_id=question.id,
        retrieved=len(retrieved_names),
        precision_at_k=hits / len(retrieved_names),
        document_recall=len(found) / len(expected) if expected else 0.0,
        **coverage,
        **facts,
    )


def score_answer(
    question: GoldenQuestion,
    answer: Answer,
    *,
    document_names: dict[str, str],
) -> AnswerScore:
    cited_names = {
        document_names.get(citation.document_id, "?") for citation in answer.citations
    }
    expected = set(question.expect_documents)

    unexpected = bool(cited_names - expected) if expected else bool(cited_names)

    lowered = answer.text.lower()
    required = question.expect_contains
    coverage = (
        sum(1 for phrase in required if phrase.lower() in lowered) / len(required)
        if required
        else 1.0
    )

    return AnswerScore(
        question_id=question.id,
        grounded_as_expected=answer.grounded == question.expect_grounded,
        citation_accuracy=(
            len(cited_names & expected) / len(cited_names) if cited_names else 0.0
        ),
        content_coverage=coverage,
        cited_unexpected_document=unexpected,
        cost_usd=float(answer.usage.cost_usd),
        latency_ms=answer.latency_ms,
    )


class Report(BaseModel):
    """Aggregate over one strategy's run of the golden set.

    Milestone 4 extends this to hold four of them side by side; the per-question
    detail is retained so a regression can be traced to the question that caused
    it rather than to a moved average.
    """

    strategy: str
    mode: str = ""
    results: list[QuestionResult] = Field(default_factory=list)
    # True for a report that scored retrieval without generating answers — the
    # decomposition ceiling. Flagged rather than inferred from all-zero answer
    # scores, because "no answer was generated" and "every answer was wrong" are
    # opposite facts that would otherwise render identically.
    retrieval_only: bool = False

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def mean_precision(self) -> float:
        """Averaged over answerable questions only.

        Including unanswerable ones would reward retrieving nothing, and a system
        that retrieved nothing for everything would score perfectly.
        """
        scores = [
            r.retrieval.precision_at_k
            for r in self.results
            if not r.question.is_unanswerable
        ]
        return sum(scores) / len(scores) if scores else 0.0

    @property
    def mean_document_recall(self) -> float:
        scores = [
            r.retrieval.document_recall
            for r in self.results
            if not r.question.is_unanswerable
        ]
        return sum(scores) / len(scores) if scores else 0.0

    @property
    def groundedness_agreement(self) -> float:
        if not self.results:
            return 0.0
        agreed = sum(1 for r in self.results if r.answer.grounded_as_expected)
        return agreed / len(self.results)

    @property
    def retrieval_pass_rate(self) -> float:
        """The number the Milestone 0 gate is set against.

        Measurable offline, because retrieval is entirely real under the fake
        providers — real chunking, real index, real similarity search.
        """
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.retrieval_passed) / len(self.results)

    @property
    def cited_unexpected(self) -> int:
        """Citations pointing at a document the question does not need.

        A retrieval-precision signal rather than a fabrication one — see
        `AnswerScore.cited_unexpected_document`.
        """
        return sum(1 for r in self.results if r.answer.cited_unexpected_document)

    @property
    def ungrounded_handled(self) -> tuple[int, int]:
        """(correct, total) over the deliberately unanswerable questions.

        Tracked separately because it is the one thing that must never regress:
        an answer invented for a question the documents do not cover is the single
        most damaging failure a teaching RAG platform can produce.
        """
        unanswerable = [r for r in self.results if r.question.is_unanswerable]
        correct = sum(1 for r in unanswerable if r.answer.grounded_as_expected)
        return correct, len(unanswerable)

    @property
    def total_cost_usd(self) -> float:
        return sum(r.answer.cost_usd for r in self.results)

    def retrieval_kind_breakdown(self) -> dict[str, tuple[int, int]]:
        """passed/total per kind, judged on retrieval alone.

        For a report that generated no answers — the decomposition ceiling — this
        is the only verdict that exists. `kind_breakdown` would report every kind
        as a total failure, since `passed` requires an answer nobody asked for.
        """
        out: dict[str, tuple[int, int]] = {}
        for result in self.results:
            passed, total = out.get(result.question.kind, (0, 0))
            out[result.question.kind] = (
                passed + int(result.retrieval_passed),
                total + 1,
            )
        return out

    def kind_breakdown(self) -> dict[str, tuple[int, int]]:
        """passed/total per question kind.

        The breakdown is where the teaching lives: an aggregate that hides "0/2 on
        relational questions" behind a decent overall average would conceal
        exactly the weakness Milestone 2 is meant to address.
        """
        out: dict[str, tuple[int, int]] = {}
        for result in self.results:
            passed, total = out.get(result.question.kind, (0, 0))
            out[result.question.kind] = (passed + int(result.passed), total + 1)
        return out
