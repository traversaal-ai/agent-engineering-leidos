"""PRD Section 5 — student must-have:

    "I want every answer to include citations so that I can verify it's grounded
    in the documents I uploaded."

PRD Section 6 acceptance criterion:

    Given any generated answer, when it is returned to the student, then it
    includes at least one citation linking back to a specific uploaded document,
    unless no relevant content was found — in which case the answer states that
    explicitly instead of fabricating a citation.

Milestone 0.

The "unless" clause is the whole substance of this criterion, and it is why the
second test matters more than the first. A system that always cites is easy; a
system that knows when it *cannot* cite, and says so rather than inventing a
plausible source, is the actual requirement. The failure mode being guarded
against — an answer with a confident citation to a document that does not support
it — is the single most damaging thing a teaching RAG platform could do, because
a student learning to trust citations would learn the wrong lesson.
"""

from __future__ import annotations

import httpx
import pytest

from ai_backend.contracts.models import Strategy
from tests.docfixtures import make_pdf

pytestmark = [pytest.mark.story("citations on every answer"), pytest.mark.milestone(0)]

# Which milestone delivered each strategy, used only to tag the cases for
# `--milestone N`. Kept here rather than imported from the choose-strategy module so
# each acceptance module stays readable on its own.
_SCHEDULE: dict[Strategy, int] = {
    Strategy.NAIVE_RAG: 0,
    Strategy.AGENTIC_RAG: 1,
}
assert set(_SCHEDULE) == set(Strategy), "every Strategy needs a case in _SCHEDULE"

# Real documents, not byte strings that merely start with "%PDF". A parser rightly
# refuses the latter, so a test built on one would assert against a document that
# never indexed — see tests/docfixtures.py.
_LEAVE_POLICY = (
    "Parental leave. Employees are entitled to 16 weeks of paid parental leave "
    "following the birth or adoption of a child. Leave may be taken in up to "
    "three separate blocks within the first year."
)
_CHEESE = (
    "A history of alpine cheese. Hard mountain cheeses have been produced in "
    "high pastures since the fourteenth century, matured in cellars for up to "
    "eighteen months."
)


async def test_a_grounded_answer_cites_a_real_uploaded_document(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    session_id = str(session["session_id"])

    upload = await client.post(
        f"/api/v1/sessions/{session_id}/documents",
        files=[("files", ("policy.pdf", make_pdf(_LEAVE_POLICY), "application/pdf"))],
        headers=auth,
    )
    assert upload.status_code == 200, upload.text
    document_id = upload.json()["documents"][0]["document_id"]

    response = await client.post(
        f"/api/v1/sessions/{session_id}/query",
        json={"question": "How long is parental leave?", "strategy": Strategy.NAIVE_RAG.value},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["grounded"] is True
    assert len(body["citations"]) >= 1, "a grounded answer must cite at least once"

    # "linking back to a specific uploaded document" — the citation must point at
    # a document this session actually holds. A citation to a plausible-looking
    # id that was never uploaded would satisfy a weaker check and be worse than
    # no citation at all.
    cited = {c["document_id"] for c in body["citations"]}
    assert document_id in cited, f"cited {cited}, expected {document_id}"

    for citation in body["citations"]:
        assert citation["filename"] == "policy.pdf"
        # Somewhere a student can actually go and look.
        assert citation["source_location"], "a citation needs a locatable origin"


async def test_an_ungrounded_answer_says_so_and_cites_nothing(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """The "unless" clause: no relevant content, so say so — do not invent a source."""
    session_id = str(session["session_id"])

    await client.post(
        f"/api/v1/sessions/{session_id}/documents",
        files=[("files", ("cheese.pdf", make_pdf(_CHEESE), "application/pdf"))],
        headers=auth,
    )

    response = await client.post(
        f"/api/v1/sessions/{session_id}/query",
        json={
            "question": "What is the company's stance on quantum cryptography?",
            "strategy": Strategy.NAIVE_RAG.value,
        },
        headers=auth,
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["grounded"] is False
    assert body["citations"] == [], "an ungrounded answer must fabricate no citations"
    # "states that explicitly" — the student must be told, in the answer text,
    # that nothing relevant was found.
    assert any(
        phrase in body["answer"].lower()
        for phrase in ("not find", "no relevant", "nothing relevant", "couldn't find",
                       "could not find", "no sufficiently relevant")
    ), body["answer"]


async def test_no_relevant_content_is_visible_in_the_trace(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """System Design Section 11 requires the empty retrieval be a visible step.

    Not an exception and not a silent empty list — a step a student can see, so
    "why did it say that?" has an answer on screen.
    """
    session_id = str(session["session_id"])
    await client.post(
        f"/api/v1/sessions/{session_id}/documents",
        files=[("files", ("cheese.pdf", make_pdf(_CHEESE), "application/pdf"))],
        headers=auth,
    )

    body = (
        await client.post(
            f"/api/v1/sessions/{session_id}/query",
            json={"question": "Quantum cryptography policy?", "strategy": Strategy.NAIVE_RAG.value},
            headers=auth,
        )
    ).json()

    steps = (
        await client.get(
            f"/api/v1/sessions/{session_id}/trace/steps",
            params={"trace_id": body["trace_id"]},
            headers=auth,
        )
    ).json()

    retrievals = [s for s in steps if s["step_type"] == "retrieve"]
    assert retrievals, "retrieval must appear in the trace even when it finds nothing"
    assert any(
        "no sufficiently relevant" in (s.get("raw_output") or "").lower()
        or s["attributes"].get("chunks_found") == 0
        for s in retrievals
    ), retrievals


# Parametrized per strategy rather than one blanket marker, so each turns green at its
# own milestone. The earlier version inherited the module's milestone(0) while carrying
# a Milestone 3 xfail, which put it in the M0 slice as something that could never pass
# there — and once Naive RAG landed it XPASSed and failed the build, which is how the
# mismatch surfaced.
@pytest.mark.parametrize(
    "strategy",
    [
        pytest.param(
            strategy, marks=[pytest.mark.milestone(milestone)], id=strategy.value
        )
        for strategy, milestone in _SCHEDULE.items()
    ],
)
async def test_every_strategy_cites(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str], strategy: Strategy
) -> None:
    """"any generated answer" means both strategies, not just the baseline.

    The requirement is identical for each, and that is the point: a Compare table where
    one strategy cites and the other does not would make the comparison unreadable —
    a reader could not tell whether the orchestration bought a better answer or just a
    less accountable one.
    """
    session_id = str(session["session_id"])
    await client.post(
        f"/api/v1/sessions/{session_id}/documents",
        files=[("files", ("policy.pdf", make_pdf(_LEAVE_POLICY), "application/pdf"))],
        headers=auth,
    )

    body = (
        await client.post(
            f"/api/v1/sessions/{session_id}/query",
            json={"question": "How long is parental leave?", "strategy": strategy.value},
            headers=auth,
        )
    ).json()

    assert body["grounded"] is True
    assert len(body["citations"]) >= 1, f"{strategy.value} returned no citations"
