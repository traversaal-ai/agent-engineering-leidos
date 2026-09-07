"""GET /api/v1/demo/questions — the labelled demo question set.

PRD Section 6, *Predicted-outcome question set*: each demo question carries the
outcome a student should expect before pressing Ask, and that prediction is one the
evaluation harness verifies rather than one asserted in a template.

**Why the Backend serves it rather than the Frontend holding it.** The labels are
derived from the golden set (`ai_backend/evaluation/demo.py`), and the Frontend may
not import `ai_backend` at all — layer rule 1, enforced by
`tests/unit/test_layer_boundaries.py`. Hardcoding the questions into a Jinja template
would satisfy the layer rule and break the criterion instead: the labels would no
longer be derived from anything, and the harness could not fail when one stopped
being true. So they travel over HTTP like every other piece of data the Frontend
renders.

**No auth, like `/health`.** The question set is static, non-sensitive, identical for
every session, and the Frontend needs it to render the page *before* a session
necessarily exists — a student arrives at `/` before they have done anything.
Requiring a token would mean minting a session just to draw a list of four sentences.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ai_backend.config.settings import Settings
from backend import dispatch
from backend.schemas.demo import (
    DemoQuestionOut,
    DemoQuestionsResponse,
    PainPointOut,
    PainPointsResponse,
)

router = APIRouter(tags=["demo"])


@router.get("/demo/questions", response_model=DemoQuestionsResponse)
async def demo_questions() -> DemoQuestionsResponse:
    """The labelled questions, in the order a class should meet them.

    The order is the lesson plan and is decided in the AI Backend, not here — see
    `ai_backend/evaluation/demo.py`. This route does not sort, filter or pad the
    list; a set with three outcomes instead of four is reported as three, because
    inventing a fourth would mean promising an outcome nothing measured.
    """
    return DemoQuestionsResponse(
        questions=[DemoQuestionOut(**q) for q in dispatch.demo_question_set()],
        documents=[d.filename for d in dispatch.demo_document_set()],
    )


@router.get("/demo/pain-points", response_model=PainPointsResponse)
async def pain_points(request: Request) -> PainPointsResponse:
    """The four ways naive RAG fails, each with the run that demonstrates it.

    Unauthenticated for the same reasons as `/demo/questions` above: static,
    identical for every session, and needed to render the page before a session
    exists.

    The list is derived from the golden set rather than written here, so every claim
    on the page is one `--compare-strategies` verifies. A pain point whose question
    has gone missing is reported as absent rather than padded — see
    `ai_backend/evaluation/demo.py::pain_point_demos`.

    **`settings` is passed rather than looked up**, because whether a card may state a
    measurement depends on the conditions it was measured under — the embedding model,
    `top_k`, `min_similarity` and the corpus. Reading process-wide settings inside the
    evaluation module would mean the answer came from somewhere other than the app that
    is actually running, which is the class of mistake the whole verdict mechanism
    exists to catch.
    """
    settings: Settings = request.app.state.settings
    return PainPointsResponse(
        pain_points=[
            PainPointOut(**p) for p in dispatch.pain_point_set(settings=settings)
        ],
        documents=[d.filename for d in dispatch.demo_document_set()],
    )
