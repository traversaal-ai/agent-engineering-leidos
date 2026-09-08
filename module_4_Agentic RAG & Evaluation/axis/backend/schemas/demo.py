"""The labelled demo question set, on the wire.

`outcome` is a plain string rather than the AI Backend's `PredictedOutcome` enum,
deliberately. The Frontend renders it as a CSS hook and a badge and must keep
working if the evaluation module gains a fifth outcome — a stricter wire type would
turn "the AI Backend learned a new label" into a 500 from the Backend, which is the
wrong layer to fail in and the wrong failure to have. The set of valid values is
documented by `ai_backend/evaluation/demo.py`, not enforced here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DemoQuestionOut(BaseModel):
    id: str
    question: str
    # Which strategy should win: agentic_wins | naive_wins | tie | both_refuse.
    outcome: str
    # Why, in a sentence the student reads *before* running it. A prediction whose
    # reasoning only arrives afterwards is a description.
    because: str


class DemoQuestionsResponse(BaseModel):
    questions: list[DemoQuestionOut] = Field(default_factory=list)
    # The filenames the predictions were measured against.
    #
    # Sent so the Frontend can offer the questions only once those documents are
    # actually indexed. A predicted outcome is a claim about a specific corpus —
    # "splitting this question finds a document the blended search misses" is only
    # true of documents that make it true — and showing it beside somebody's own
    # unrelated PDFs would have the platform confidently predicting the wrong thing.
    documents: list[str] = Field(default_factory=list)


class PainPointOut(BaseModel):
    """One of naive RAG's four failure modes, with the run that shows it."""

    id: str
    # A short name for the card. Not the material's own bolded name, which is a full
    # phrase — see `_TITLES` in `ai_backend/evaluation/demo.py` for why, and for what
    # carries the material's wording instead.
    title: str
    # The course material's own wording. Quoted rather than paraphrased so a student
    # who read it last week recognises the sentence.
    symptom: str
    mechanism: str
    # What the harness measured, in a sentence — the figures read from the recorded
    # verdict, the explanation written. Phrased as a measurement rather than a bare
    # number, because the number alone invites the wrong summary.
    #
    # **Empty when nothing measured it.** A card used to keep its sentence when the
    # harness stopped being able to demonstrate the mechanism, which made it a claim
    # rather than a measurement; the two fields below say why there is no figure.
    measured: str = ""
    verified_by_harness: bool = True
    unverified_reason: str = ""
    question: str
    # Present only on the memory demo, which is why that one runs two queries per
    # strategy rather than one.
    context_question: str = ""
    # The golden question this card is bound to, so a reader can find what verifies it.
    golden_id: str = ""


class PainPointsResponse(BaseModel):
    pain_points: list[PainPointOut] = Field(default_factory=list)
    # Same reason as `DemoQuestionsResponse.documents`: these demonstrations are
    # claims about a specific corpus, so the Frontend can decline to offer them
    # until that corpus is indexed.
    documents: list[str] = Field(default_factory=list)
