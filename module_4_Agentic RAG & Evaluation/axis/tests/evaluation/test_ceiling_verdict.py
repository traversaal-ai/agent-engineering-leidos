"""The recorded verdict, and the page's right to claim a measurement.

**What this guards, stated plainly.** `--compare-strategies` exits non-zero when a
mechanism stops earning its cost. That gate protected nothing a student could see: it
printed to a terminal and persisted nothing, so when the decomposition and hop ceilings
went to `+0.00` under a real embedding model, two *Why agentic* cards carried on stating
"asked whole, this retrieves neither document" against a measured 1.00. The gate was red
and not one word on screen changed.

Nothing in the suite could have caught that, because the claims were prose and prose
cannot fail. These tests exist so it cannot happen twice.
"""

from __future__ import annotations

import json

import pytest

from ai_backend.config.settings import Settings
from ai_backend.evaluation.demo import PainPoint, pain_point_demos
from ai_backend.evaluation.verdict import (
    CeilingVerdict,
    QuestionDelta,
    Trust,
    conditions_now,
    corpus_fingerprint,
    load_verdict,
    trust_for,
    write_verdict,
)

pytestmark = [
    pytest.mark.story("four ways naive RAG fails"),
    pytest.mark.milestone(4),
]


def _holds(unit: str, question_id: str, before: float = 0.0) -> CeilingVerdict:
    return CeilingVerdict(
        unit=unit,
        improved=1,
        eligible=1,
        questions=[QuestionDelta(question_id=question_id, before=before, after=1.0)],
    )


def _all_hold() -> dict[str, CeilingVerdict]:
    return {
        "decomposition": _holds("recall", "ceiling-vs-nte"),
        "hop": _holds("recall", "deliverable-at-risk"),
        "resolution": _holds("recall", "agreement-term"),
        "coverage": _holds("coverage", "summarize-program", before=0.13),
    }


# -- the record itself ------------------------------------------------------


def test_a_ceiling_that_improved_nothing_does_not_hold() -> None:
    """The same condition the CLI gates on, in the object the page reads.

    Both halves matter and the second is the one worth stating: **no eligible question
    is a failure, not a vacuous pass.** It means the golden set lost the question a
    mechanism was demonstrated on, and the page would still be offering it.
    """
    assert _holds("recall", "ceiling-vs-nte").holds

    assert not CeilingVerdict(unit="recall", improved=0, eligible=3).holds
    assert not CeilingVerdict(unit="recall", improved=0, eligible=0).holds


def test_the_corpus_fingerprint_follows_the_loader(tmp_path) -> None:
    """Hashed through `demo_documents()`, not a fresh glob of `data/`.

    A fingerprint that globbed independently would describe a set nothing reads — and
    the corpus directory has one file in it that is deliberately *not* corpus
    (`README.md`). The point of the hash is to notice an edit to what actually gets
    indexed.
    """
    first = corpus_fingerprint()

    assert len(first) == 64, "not a sha256 digest"
    assert first == corpus_fingerprint(), "the fingerprint is not stable"


def test_an_unreadable_record_is_no_record(tmp_path) -> None:
    """Read while a page renders, so a broken file is `None` rather than a 500.

    The honest answer to "is this claim verified" when the record cannot be read is
    *no*. Raising would take the page down over a file whose only job is to withhold a
    sentence.
    """
    missing = tmp_path / "absent.json"
    assert load_verdict(missing) is None

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_verdict(broken) is None

    wrong_shape = tmp_path / "wrong.json"
    wrong_shape.write_text(json.dumps({"ceilings": "no"}), encoding="utf-8")
    assert load_verdict(wrong_shape) is None


def test_the_recorded_verdict_is_the_one_the_table_printed() -> None:
    """The table, the exit code and the file must be one computation.

    `_render_ceiling_delta`'s own docstring makes this argument about the first two —
    *"a gate computed separately from the table it is printed beside is a gate that can
    disagree with the evidence for it"* — and the file is now a third thing that could
    disagree. So the block and the verdict are checked against each other: whatever the
    printed summary line says improved, the record says too.
    """
    from ai_backend.evaluation.__main__ import _render_ceiling_delta
    from ai_backend.evaluation.golden import GoldenQuestion
    from ai_backend.evaluation.runner import Ceiling
    from ai_backend.evaluation.scoring import (
        AnswerScore,
        QuestionResult,
        Report,
        RetrievalScore,
    )

    question = GoldenQuestion(
        id="ceiling-vs-nte",
        question="Compare the ceiling with the not-to-exceed value.",
        kind="comparison",
        expect_documents=["a", "b"],
        sub_questions=["What is the ceiling?", "What is the NTE?"],
        expect_passages=["$48,500,000", "$13,268,000"],
    )

    def report(strategy: str, facts: int) -> Report:
        return Report(
            strategy=strategy,
            results=[
                QuestionResult(
                    question=question,
                    retrieval=RetrievalScore(
                        question_id=question.id,
                        # Perfect on the old measure in *both* runs, which is the
                        # whole reason this ceiling moved off it.
                        document_recall=1.0,
                        facts_found=facts,
                        facts_required=2,
                    ),
                    answer=AnswerScore(question_id=question.id),
                )
            ],
        )

    block, measured = _render_ceiling_delta(
        report("naive_rag", 1), report("ceiling", 2), Ceiling.DECOMPOSITION
    )
    assert measured.improved == 1 and measured.eligible == 1
    assert measured.unit == "facts", "the recorded number carries no unit"
    assert "improved facts on 1/1 question(s)" in block
    assert measured.holds
    assert measured.questions[0].before == 0.5
    assert measured.questions[0].after == 1.0

    # And the state that started this: measured, printed and recorded as no gain.
    block, measured = _render_ceiling_delta(
        report("naive_rag", 2), report("ceiling", 2), Ceiling.DECOMPOSITION
    )
    assert measured.improved == 0
    assert "improved facts on 0/1 question(s)" in block
    assert "bought nothing" in block
    assert not measured.holds, (
        "the record says the mechanism holds while the table printed that it bought "
        "nothing — the page would then claim a figure the terminal just refuted"
    )


def test_fact_recall_counts_retrieved_facts_not_documents() -> None:
    """**The blindness, pinned.** This is the measurement bug in one assertion.

    A retrieval that reaches one chunk from each of the two expected documents scores a
    perfect `document_recall` — the metric is `len(expected & retrieved) / len(expected)`
    and every compound question in the set names exactly two documents, so it is
    three-valued and one lucky chunk each saturates it.

    But a comparison that reached only one of the two figures being compared has not
    answered the question. Under a real embedding model that is exactly what a single
    blended query does, which is why the decomposition and hop ceilings reported `+0.00`
    for months of embedder while the mechanisms worked fine. `fact_recall` is what tells
    the two apart, and this asserts both numbers on the same retrieval so the difference
    cannot be argued away.
    """
    from ai_backend.contracts.models import Chunk, RetrievedContext
    from ai_backend.evaluation.golden import GoldenQuestion
    from ai_backend.evaluation.scoring import score_retrieval

    question = GoldenQuestion(
        id="ceiling-vs-nte",
        question="Compare the ceiling with the not-to-exceed value.",
        kind="comparison",
        expect_documents=["msa", "sow"],
        expect_passages=["$48,500,000", "$13,268,000"],
    )
    names = {"doc-msa": "msa", "doc-sow": "sow"}

    half = RetrievedContext(
        chunks=[
            Chunk(document_id="doc-msa", content="The aggregate ceiling is $48,500,000."),
            # From the right document, and carrying none of what the question needs.
            Chunk(document_id="doc-sow", content="Deliverables are reviewed monthly."),
        ]
    )
    score = score_retrieval(question, half, document_names=names)

    assert score.document_recall == 1.0, "both documents were reached"
    assert score.fact_recall == 0.5, "only one of the two figures came back"

    both = RetrievedContext(
        chunks=[
            Chunk(document_id="doc-msa", content="The aggregate ceiling is $48,500,000."),
            Chunk(document_id="doc-sow", content="**Not-to-exceed:** $13,268,000"),
        ]
    )
    assert score_retrieval(question, both, document_names=names).fact_recall == 1.0

    # Nothing retrieved is 0 of 2, not 0 of 0 — the second reads as "this question
    # required nothing", which is a friendlier claim than the truth.
    empty = score_retrieval(question, RetrievedContext(), document_names=names)
    assert empty.facts_required == 2 and empty.facts_found == 0
    assert empty.fact_recall == 0.0


def test_a_question_declaring_no_facts_is_not_scored_on_them() -> None:
    """0/0, and `fact_recall` of 0.0 — which is why only two ceilings read it.

    For a question about one fact in one place, "did both facts come back" is not a
    question, and a measure that reported 0.00 for it would look like a failure.
    """
    from ai_backend.contracts.models import Chunk, RetrievedContext
    from ai_backend.evaluation.golden import GoldenQuestion
    from ai_backend.evaluation.scoring import score_retrieval

    question = GoldenQuestion(
        id="payment-terms",
        question="When is payment due?",
        kind="factual",
        expect_documents=["msa"],
    )
    score = score_retrieval(
        question,
        RetrievedContext(chunks=[Chunk(document_id="doc-msa", content="Net 45.")]),
        document_names={"doc-msa": "msa"},
    )

    assert score.facts_required == 0 and score.facts_found == 0
    assert score.document_recall == 1.0


def test_every_declared_fact_is_actually_in_the_corpus() -> None:
    """A wrong string makes a working mechanism look broken, silently.

    `expect_passages` is ground truth authored by hand against the documents, and a
    typo in one produces a ceiling that reports a mechanism buying less than it does —
    with nothing anywhere saying why. Each declared fact must appear in the corpus, and
    in exactly one document, or it is not identifying the passage it claims to.
    """
    from ai_backend.evaluation.golden import demo_documents, load_golden_set

    corpus = {d.filename: d.data.decode("utf-8") for d in demo_documents()}

    for question in load_golden_set().questions:
        for fact in question.expect_passages:
            holders = [name for name, text in corpus.items() if fact in text]
            assert holders, (
                f"{question.id} requires {fact!r}, which appears in no document — "
                f"retrieval can never satisfy it and the mechanism will read as broken"
            )
            assert len(holders) == 1, (
                f"{question.id} requires {fact!r}, which appears in {holders}. A fact "
                f"in more than one document identifies no particular passage, so "
                f"reaching it proves nothing about which side was retrieved."
            )


# -- conditions -------------------------------------------------------------


def test_a_report_measured_under_other_conditions_is_not_trusted(
    tmp_path, settings: Settings
) -> None:
    """**The regression that matters most: a stale record lies with authority.**

    A figure is not a fact about a mechanism. It is a fact about one mechanism, one
    embedding model, one corpus and one `top_k` — and this whole defect began with the
    `0.00` baselines the compound questions were chosen on, which were
    `FakeEmbeddingProvider` threshold rejections that nothing recorded as such.

    So a mismatch reads as *no measurement*, never as a passing one. Checked here in
    each direction a person actually changes: the embedder, the retrieval knobs, and the
    corpus.
    """
    path = tmp_path / "ceilings.json"
    write_verdict(_all_hold(), settings=settings, path=path)

    trust, _ = trust_for("decomposition", settings=settings, path=path)
    assert trust is Trust.VERIFIED, "a matching record should be trusted"

    for changed in (
        settings.model_copy(update={"embedding": settings.embedding.model_copy(
            update={"model": "text-embedding-3-large"}
        )}),
        settings.model_copy(update={"embedding": settings.embedding.model_copy(
            update={"provider": "openai"}
        )}),
        settings.model_copy(update={"retrieval": settings.retrieval.model_copy(
            update={"top_k": 8}
        )}),
        settings.model_copy(update={"retrieval": settings.retrieval.model_copy(
            update={"min_similarity": 0.4}
        )}),
        settings.model_copy(update={"retrieval": settings.retrieval.model_copy(
            update={"hybrid": True}
        )}),
    ):
        trust, measured = trust_for("decomposition", settings=changed, path=path)
        assert trust is Trust.CONDITIONS_CHANGED, (
            "a measurement taken under other settings was reported as verifying this "
            "configuration"
        )
        assert measured is None, "a mismatched record still handed over its figures"


def test_an_edited_corpus_invalidates_the_record(tmp_path, settings: Settings) -> None:
    """The change least likely to be noticed, and the reason the hash is in there.

    Re-copying the originals over `data/` is exactly the edit `data/README.md` warns
    about: no error, no failed request, quietly worse retrieval. A recorded figure taken
    before it is not a claim about the corpus after it.
    """
    path = tmp_path / "ceilings.json"
    record = write_verdict(_all_hold(), settings=settings, path=path)

    stale = record.model_copy(
        update={
            "conditions": record.conditions.model_copy(
                update={"corpus": "0" * 64}
            )
        }
    )
    path.write_text(stale.model_dump_json(indent=2), encoding="utf-8")

    trust, _ = trust_for("decomposition", settings=settings, path=path)
    assert trust is Trust.CONDITIONS_CHANGED


def test_conditions_record_what_the_figure_is_true_of(settings: Settings) -> None:
    """Every field here has changed at least once in this project's life."""
    conditions = conditions_now(settings)

    assert conditions.embedding_provider == settings.embedding.provider
    assert conditions.embedding_model == settings.embedding.model
    assert conditions.top_k == settings.retrieval.top_k
    assert conditions.min_similarity == settings.retrieval.min_similarity
    assert conditions.hybrid == settings.retrieval.hybrid
    assert conditions.corpus == corpus_fingerprint()


# -- what the card is allowed to say ----------------------------------------


def test_a_card_with_no_verified_mechanism_claims_no_measurement(
    tmp_path, settings: Settings
) -> None:
    """**The defect itself, pinned.** Prose must not survive a red gate.

    Three ways a card can have nothing to claim, and all three must produce an empty
    `measured` — not a sentence someone wrote when the mechanism last worked. The reason
    differs in each case because the remedy does: run the harness, put the settings
    back, or accept that this corpus no longer demonstrates this.
    """
    absent = tmp_path / "never-run.json"
    for demo in pain_point_demos(settings=settings, verdict=load_verdict(absent)):
        assert demo.measured == "", f"{demo.id} claims a measurement with no record"
        assert not demo.verified_by_harness
        assert demo.unverified_reason, f"{demo.id} gives no reason for having no figure"
        # The card still teaches: only the figure is missing.
        assert demo.symptom and demo.mechanism and demo.question

    # A ceiling that ran and bought nothing — the state that started all this.
    path = tmp_path / "ceilings.json"
    failing = _all_hold()
    failing["decomposition"] = CeilingVerdict(
        unit="recall",
        improved=0,
        eligible=1,
        questions=[
            QuestionDelta(question_id="ceiling-vs-nte", before=1.0, after=1.0)
        ],
    )
    write_verdict(failing, settings=settings, path=path)
    record = load_verdict(path)

    by_id = {d.id: d for d in pain_point_demos(settings=settings, verdict=record)}
    assert by_id[PainPoint.COMPARE.value].measured == "", (
        "the comparison card kept its sentence after the mechanism stopped paying off "
        "— which is exactly what it did in production"
    )
    assert not by_id[PainPoint.COMPARE.value].verified_by_harness
    # And the other three are untouched: one failing ceiling is not four.
    assert by_id[PainPoint.SUMMARIZE.value].measured
    assert by_id[PainPoint.REMEMBER.value].measured


def test_a_verified_card_quotes_the_recorded_figures(
    tmp_path, settings: Settings
) -> None:
    """The numbers on the card come from the record, not from the source.

    This is the half that makes the card a measurement rather than a claim: change the
    recorded figure and the sentence changes with it. If it does not, the sentence is
    prose again and the whole mechanism is decoration.
    """
    path = tmp_path / "ceilings.json"
    ceilings = _all_hold()
    ceilings["decomposition"] = CeilingVerdict(
        unit="recall",
        improved=1,
        eligible=1,
        questions=[
            QuestionDelta(question_id="ceiling-vs-nte", before=0.5, after=1.0)
        ],
    )
    write_verdict(ceilings, settings=settings, path=path)

    by_id = {
        d.id: d for d in pain_point_demos(settings=settings, verdict=load_verdict(path))
    }
    compare = by_id[PainPoint.COMPARE.value]

    assert compare.verified_by_harness
    # **Each card speaks in the unit its ceiling measured.** Comparison is scored on
    # facts, so it says how many of them came back; a fraction like "0.50" would be a
    # ratio the reader has to decode, and "documents" would name a measurement nobody
    # took. Coverage speaks in percentages, because "0.13 of the chunks" is not a
    # quantity anyone can picture.
    assert "1 of the 2 facts" in compare.measured, compare.measured
    assert "both" in compare.measured, compare.measured
    # The old wording, which described the figure as document recall. The card may
    # still *mention* documents — "it lands on both documents and on neither of the
    # figures" is the lesson — but the quantity must not be counted in them.
    assert "documents this needs" not in compare.measured
    assert "13%" in by_id[PainPoint.SUMMARIZE.value].measured

    # Move the recorded figure and the sentence must move with it — otherwise it is
    # prose again and the whole mechanism is decoration.
    ceilings["decomposition"].questions[0].before = 0.0
    write_verdict(ceilings, settings=settings, path=path)
    again = {
        d.id: d for d in pain_point_demos(settings=settings, verdict=load_verdict(path))
    }
    assert "0 of the 2 facts" in again[PainPoint.COMPARE.value].measured
