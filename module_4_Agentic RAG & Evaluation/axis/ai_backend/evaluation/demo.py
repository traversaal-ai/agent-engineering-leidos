"""The labelled demo question set — questions that carry a predicted outcome.

**Why this exists.** PRD Section 7 records the risk that *"students may conflate
'agentic' or 'graph-based' with 'always better' if demo questions aren't chosen
deliberately"*, and Goal 1 measures whether a student can pick the right strategy for
a **scenario**. Nothing in the product taught scenario→strategy mapping: a student
typed a question, watched agentic cost three times as much, and — because a
single-fact question is the obvious thing to type first — reliably concluded that
orchestration is never worth it. That is as wrong as the misconception it replaces,
and it is the lesson the platform was accidentally teaching.

**Why the labels are derived rather than written.** A hand-written label is a claim
in a template that nothing checks, and the first retrieval change that invalidates it
leaves a teaching tool confidently predicting the wrong outcome. So the outcome is
derived from what the golden set already *declares* about each question — how many
documents it needs, whether a ground-truth decomposition exists, whether it is
answerable at all — and `--compare-strategies` verifies the one prediction that could
drift. If splitting a compound question stops improving document recall, the harness
fails; it does not silently keep promising a win.

The set is deliberately small. Four outcomes is the whole space a two-strategy
comparison has, and one question per outcome is what fits on a projector.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from ai_backend.config.settings import Settings
from ai_backend.evaluation.golden import GoldenQuestion, GoldenSet, load_golden_set
from ai_backend.evaluation.runner import Ceiling
from ai_backend.evaluation.verdict import (
    CeilingVerdict,
    QuestionDelta,
    Trust,
    Verdict,
    load_verdict,
    trust_for,
)


class PredictedOutcome(StrEnum):
    """What a student should expect before they press Ask.

    Four values because that is the complete space for a two-strategy comparison:
    one strategy wins, the other wins, they tie, or neither succeeds. `NAIVE_WINS`
    means "same answer, less money" rather than a better answer — there is no
    question on which single-shot retrieval finds *more*, and pretending otherwise
    would be the mirror image of the misconception this set exists to correct.
    """

    AGENTIC_WINS = "agentic_wins"
    NAIVE_WINS = "naive_wins"
    TIE = "tie"
    BOTH_REFUSE = "both_refuse"


_EXPLANATION = {
    PredictedOutcome.AGENTIC_WINS: (
        "Two separate things to look up. One blended search finds material for one "
        "of them; splitting the question first finds both. This is what the extra "
        "cost buys."
    ),
    PredictedOutcome.NAIVE_WINS: (
        "One fact, in one place. Both strategies find it and give the same answer — "
        "the agentic run just routed, decomposed and paid three times as much to "
        "get there."
    ),
    PredictedOutcome.TIE: (
        "Both strategies reach the same source and answer equally well. Orchestration "
        "is not free and here it changes nothing."
    ),
    PredictedOutcome.BOTH_REFUSE: (
        "The documents do not cover this. Both strategies say so rather than "
        "inventing an answer — agency cannot conjure knowledge that was never "
        "indexed."
    ),
}


class DemoQuestion(BaseModel):
    """A question plus the outcome a student should predict for it."""

    id: str
    question: str
    outcome: PredictedOutcome
    # Why this outcome is expected, in a sentence a student reads *before* running
    # it. The prediction is worthless as teaching if the reasoning arrives only
    # afterwards — at that point it is a description, not a prediction.
    because: str

    @property
    def label(self) -> str:
        return self.outcome.value


def predict(question: GoldenQuestion) -> PredictedOutcome:
    """The outcome the golden set's own declarations imply.

    Ordered most-specific first. Unanswerable is checked before anything else
    because an unanswerable question can also be compound, and "neither strategy
    finds anything" is the outcome that actually occurs — a decomposed search of
    documents that do not cover the question finds nothing twice.

    **Every mechanism with a ceiling predicts an agentic win**, and that is derived
    from the shape of the question plus a *recorded* measurement rather than from a
    convention someone maintains. This used to read "a ceiling is only in the set once
    the harness has measured the win" — an invariant held by hand, and it broke in
    silence: the decomposition and hop ceilings went to zero under a real embedding
    model and nothing on screen changed. The measurement is written down now, and
    `pain_point_demos()` reads it; see `verdict.py`.

    This had a real bug worth recording. The three clauses used to be unanswerable,
    compound-and-multi-document, then multi-document — so a multi-hop question and a
    summarization question, which span documents and carry no `sub_questions`, both
    fell through to `TIE`. The Run page then offered "orchestration changes nothing
    here" on the two questions where it changes the most. Nothing failed; the label
    was simply wrong, which is exactly the failure this module's docstring says
    derived labels exist to prevent — the derivation itself had gone out of date
    with the data.
    """
    if question.is_unanswerable:
        return PredictedOutcome.BOTH_REFUSE
    # A follow-up is meaningless on its own, so it is checked before the
    # document-count clauses: it names one document and would otherwise read as
    # "one fact, in one place", which is the opposite of what it demonstrates.
    if question.is_follow_up:
        return PredictedOutcome.AGENTIC_WINS
    if question.is_multi_hop:
        return PredictedOutcome.AGENTIC_WINS
    if question.expect_full_coverage:
        return PredictedOutcome.AGENTIC_WINS
    if question.is_compound and len(question.expect_documents) > 1:
        return PredictedOutcome.AGENTIC_WINS
    if len(question.expect_documents) > 1:
        # Spans documents but nobody authored a ground truth for any mechanism.
        # Splitting might help and might not, so predicting a winner would be a
        # guess with a label on it.
        return PredictedOutcome.TIE
    return PredictedOutcome.NAIVE_WINS


def demo_questions(golden: GoldenSet | None = None) -> list[DemoQuestion]:
    """One question per predicted outcome, in the order a class should meet them.

    The order is the lesson plan. `NAIVE_WINS` comes first because it is the
    intuition-breaker — a student expects the cleverer system to win and watches it
    lose — and `AGENTIC_WINS` second, so the pair reads as "it depends on the
    question" rather than as a verdict on agents. `BOTH_REFUSE` is last because it
    is about retrieval rather than orchestration.

    A missing outcome is skipped rather than filled with a placeholder: if the
    golden set contains no compound question, the honest thing is to offer three
    questions, not to promise a win nothing can deliver.
    """
    resolved = golden or load_golden_set()
    chosen: dict[PredictedOutcome, GoldenQuestion] = {}

    for question in resolved.questions:
        outcome = predict(question)
        # First match wins, so the set is stable as questions are appended.
        chosen.setdefault(outcome, question)

    order = (
        PredictedOutcome.NAIVE_WINS,
        PredictedOutcome.AGENTIC_WINS,
        PredictedOutcome.TIE,
        PredictedOutcome.BOTH_REFUSE,
    )
    return [
        DemoQuestion(
            id=chosen[outcome].id,
            question=" ".join(chosen[outcome].question.split()),
            outcome=outcome,
            because=_EXPLANATION[outcome],
        )
        for outcome in order
        if outcome in chosen
    ]


class PainPoint(StrEnum):
    """The four ways naive RAG fails, in the course material's own order.

    `reference/module_3_Enterprise RAG/learning-materials/reference/enterprise-rag.md`
    names these four and then hands one of them forward by name:

        Is there one pain point that this architecture only partially fixes, one
        that would still benefit from an agent actively deciding to retrieve
        *again* based on what it just found? Hold onto that question, it's exactly
        where next class's material on Agentic RAG picks up.

    Axis is that next class, which makes this enum the syllabus rather than a
    convenience. **Each is answered by a different mechanism**, and that is the
    lesson — a student who leaves believing "agentic is better" has learned less
    than one who leaves knowing which failure calls for which fix.
    """

    SUMMARIZE = "summarize"
    COMPARE = "compare"
    INFER = "infer"
    REMEMBER = "remember"


class PainPointDemo(BaseModel):
    """One pain point, the question that exhibits it, and what fixes it."""

    id: str
    # A short name for the card, so the four can be scanned and pointed at. Distinct
    # from `id`, which is a URL and DOM identifier rather than display text.
    title: str
    # The material's own words, quoted rather than paraphrased: a student who read
    # them last week should recognise the sentence.
    symptom: str
    mechanism: str
    # What the harness measured, in a sentence — **and empty when nothing did.**
    #
    # It used to be prose, hardcoded per pain point, which made it a claim rather than a
    # measurement: when the decomposition and hop ceilings stopped paying off under a
    # real embedding model, two cards carried on stating "asked whole, this retrieves
    # neither document" while the harness measured 1.00. The figures here now come from
    # the recorded verdict (`verdict.py`), and there is no wording for the case where
    # there is no verdict — `unverified_reason` says so instead.
    measured: str
    # Whether a matching recorded measurement exists. False for three different reasons —
    # never run, run under other conditions, or run and the mechanism no longer pays off —
    # and `unverified_reason` distinguishes them, because the remedies differ.
    verified_by_harness: bool = True
    unverified_reason: str = ""
    question: str
    # The turn that has to precede `question` for it to mean anything. Only the
    # memory demo has one, and it is why that card runs two queries per strategy.
    context_question: str = ""
    golden_id: str = ""

    @property
    def is_conversational(self) -> bool:
        return bool(self.context_question)


# **Deliberately not the material's own bolded names, and that is worth stating so it
# is not "fixed" back.** `enterprise-rag.md` §"Four specific pain points, each with its
# own shape" names them *"Struggles to summarize"*, *"Comparison is a headache"*,
# *"Implicit data, beyond the obvious"* and *"No memory, disconnected dialogue"* — full
# phrases, up to 33 characters, which is a sentence rather than a heading and wraps to
# two lines on a card that has to sit four-across.
#
# The quote rule CLAUDE.md sets is met one line down instead: `_SYMPTOMS` below is the
# material's *second* sentence for each, verbatim, and that is what the card face
# carries under the title. So a student who read it last week still meets the wording
# they read; what they gain is four words they can scan and an instructor can point at.
# The order and numbering are the material's.
_TITLES = {
    PainPoint.SUMMARIZE: "Summarization",
    PainPoint.COMPARE: "Comparison",
    PainPoint.INFER: "Implicit data",
    PainPoint.REMEMBER: "No memory",
}

_SYMPTOMS = {
    PainPoint.SUMMARIZE: (
        "Retrieval returns chunks, not the whole picture, and naive RAG is weak at "
        "synthesizing across many documents."
    ),
    PainPoint.COMPARE: (
        "A comparison gets embedded as one single vector and searched once, so the "
        "passages that come back skew to one side of it."
    ),
    PainPoint.INFER: (
        "The answer is not stated anywhere. It needs a second retrieval chained off "
        "what the first one found, and standard RAG retrieves once and stops."
    ),
    PainPoint.REMEMBER: (
        "Every turn is handled in isolation, so a follow-up referring back to the "
        "last one has nothing to refer to."
    ),
}

_MECHANISMS = {
    PainPoint.SUMMARIZE: "Summarize — map-reduce over every chunk, not the top few",
    PainPoint.COMPARE: "The decomposer — one lookup per side, then compare",
    PainPoint.INFER: "The router's DEPTH decision, and the ReAct loop's hop mode",
    PainPoint.REMEMBER: "Conversation history, resolved by the rewriter",
}

# Which ground-truth field on a golden question marks it as this pain point's
# demonstration. The pairing is what keeps the page honest: every claim below is
# measured by the ceiling that reads the same field (`evaluation/runner.py`).
_MARKERS = {
    PainPoint.SUMMARIZE: lambda q: q.expect_full_coverage,
    PainPoint.COMPARE: lambda q: q.is_compound and q.kind == "comparison",
    PainPoint.INFER: lambda q: q.is_multi_hop,
    PainPoint.REMEMBER: lambda q: q.is_follow_up,
}

# Which ceiling measures each card's claim. The other half of `_MARKERS`: that says
# which question demonstrates a pain point, this says which measurement verifies it.
#
# Held here rather than in the test that used to carry a copy of it, so there is one
# mapping and `test_every_pain_point_is_bound_to_a_verified_golden_question` checks that
# it is *correct* — `participates(question, ceiling)` — instead of checking it against a
# duplicate that could drift with it.
_CEILINGS = {
    PainPoint.SUMMARIZE: Ceiling.COVERAGE,
    PainPoint.COMPARE: Ceiling.DECOMPOSITION,
    PainPoint.INFER: Ceiling.HOP,
    PainPoint.REMEMBER: Ceiling.RESOLUTION,
}


def pain_point_demos(
    golden: GoldenSet | None = None,
    *,
    settings: Settings | None = None,
    verdict: Verdict | None = None,
) -> list[PainPointDemo]:
    """The four pain points, each bound to the golden question that shows it.

    **Derived, not written**, for the same reason `demo_questions` is: a
    hand-written demo is a claim in a template that nothing checks, and the first
    corpus change that invalidates it leaves a teaching tool confidently
    demonstrating nothing. Each card here names a golden question, and
    `--compare-strategies` fails if the mechanism that question exists to
    demonstrate stops improving it.

    **And the card now reads that verdict rather than assuming it.** "Derived" was only
    half true: the question binding was derived and the *measurement* was prose, so a
    failing gate left two cards asserting figures the harness had just contradicted. A
    card whose ceiling has no matching record claims no measurement at all — see
    `verdict.py` for why a record measured under other conditions counts as no record.

    A pain point whose question has gone missing is **omitted** rather than shown
    with a placeholder. Three honest cards beat four where one is furniture — and
    the harness fails in that case anyway, so the gap cannot go unnoticed.

    `verdict` is resolved once here and passed down, rather than looked up per card:
    checking it hashes the corpus, and doing that four times while a page renders would
    read five files four times over.
    """
    resolved = golden or load_golden_set()
    record = verdict if verdict is not None else load_verdict()
    demos: list[PainPointDemo] = []

    for point in PainPoint:
        marker = _MARKERS[point]
        question = next((q for q in resolved.questions if marker(q)), None)
        if question is None:
            continue
        trust, measured = trust_for(
            _CEILINGS[point].value,
            settings=settings,
            verdict=record,
        )
        figures = (
            _delta_for(measured, question.id) if trust is Trust.VERIFIED else None
        )
        demos.append(
            PainPointDemo(
                id=point.value,
                title=_TITLES[point],
                symptom=_SYMPTOMS[point],
                mechanism=_MECHANISMS[point],
                # Empty when there is nothing to report. A sentence here that survived a
                # failing gate is the whole defect this replaced.
                measured=(
                    _measured(point, question, figures)
                    if figures is not None
                    else ""
                ),
                verified_by_harness=figures is not None,
                unverified_reason=(
                    "" if figures is not None else _unverified_reason(trust, measured)
                ),
                question=" ".join(question.question.split()),
                context_question=" ".join(question.context_question.split()),
                golden_id=question.id,
            )
        )
    return demos


def _delta_for(
    measured: CeilingVerdict | None, question_id: str
) -> QuestionDelta | None:
    """This card's question inside its ceiling's record.

    A ceiling can hold several questions — decomposition has three — and a card speaks
    for exactly one of them. A ceiling that holds overall while *this* question improved
    nothing is still nothing to claim here.
    """
    if measured is None:
        return None
    found = next(
        (q for q in measured.questions if q.question_id == question_id), None
    )
    return found if found is not None and found.improved else None


def _unverified_reason(trust: Trust, measured: CeilingVerdict | None) -> str:
    """Why this card has no figure, in a sentence a student can act on.

    `Trust.reason` covers the three states. The one refinement is a ceiling that holds
    for other questions but not this one: "the harness cannot demonstrate this" is true
    of the card and would be misleading about the mechanism.
    """
    if trust is Trust.VERIFIED and measured is not None:
        return (
            "The harness measured this mechanism on other questions but not on this "
            "one, so there is no figure for the run below."
        )
    return trust.reason


def _facts(question: GoldenQuestion, fraction: float) -> str:
    """A fact-recall fraction as the count it actually is.

    "Reached 0.50" is a ratio a reader has to decode; "reached one of the two facts" is
    the thing that happened. The denominator is the question's own `expect_passages`, so
    this cannot drift from what was measured.
    """
    required = len(question.expect_passages)
    found = round(fraction * required)
    if found == required:
        return "both" if required == 2 else f"all {required}"
    return f"{found} of the {required}"


def _measured(
    point: PainPoint, question: GoldenQuestion, figures: QuestionDelta
) -> str:
    """What the harness measured for this question, in a sentence.

    **The numbers are read from the recorded verdict; only the explanation is written
    here.** That split is the fix: the sentences used to assert both, so when the
    decomposition and hop ceilings stopped paying off under a real embedding model, two
    cards went on claiming "asked whole, this retrieves neither document" against a
    measured 1.00. The mechanism clause is a fact about *why* retrieval behaves this way
    and stays prose; the figures cannot be, and now are not.

    Phrased as a measurement with its mechanism named, because the number alone invites
    the wrong summary. "Recall went from 0.00 to 1.00" reads as "agentic is twice as
    good"; "asked whole it reached neither of the two facts the answer needs, asked as
    two questions it reached both" is the thing that actually happened.

    **Comparison and Implicit data speak in *facts*, not documents**, because that is
    what their ceilings now measure — `expect_passages` rather than `document_recall`.
    Saying "documents" here while the recorded unit is `facts` would be a card
    describing a measurement nobody took, which is a smaller version of the defect this
    function was rewritten to fix.
    """
    if point is PainPoint.SUMMARIZE:
        # Coverage, so a percentage: the claim is about how much of the corpus was read,
        # and "0.13" of a thing a student cannot see is not a quantity they can picture.
        return (
            f"Asked to summarize, top-k retrieval reached "
            f"{figures.before:.0%} of the chunks these "
            f"{len(question.expect_documents)} documents hold. Summarize reads all of "
            f"them — {figures.after:.0%}."
        )
    if point is PainPoint.COMPARE:
        return (
            f"A two-part question is one blended vector, searched once. It lands on "
            f"both documents and on neither of the figures: asked whole, retrieval "
            f"reached {_facts(question, figures.before)} facts the answer needs; asked "
            f"as two questions, {_facts(question, figures.after)}."
        )
    if point is PainPoint.INFER:
        return (
            f"The second thing to search for is not named in the question, only in the "
            f"answer to the first search. Asked whole, retrieval reached "
            f"{_facts(question, figures.before)} facts the answer needs; following the "
            f"chain, {_facts(question, figures.after)}."
        )
    return (
        f"Every word in this follow-up is common, and the thing it refers to is in the "
        f"previous turn. Asked as typed, retrieval scored {figures.before:.2f}; "
        f"resolved against that turn, {figures.after:.2f}."
    )


__all__ = [
    "DemoQuestion",
    "PainPoint",
    "PainPointDemo",
    "PredictedOutcome",
    "demo_questions",
    "pain_point_demos",
    "predict",
]
