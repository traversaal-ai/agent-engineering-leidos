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


# -- the markers in the prose and the numbers on the list must agree -------


def test_a_marker_is_renumbered_to_match_the_list_it_is_shown_with() -> None:
    """A model citing [1] and [4] must not be rendered beside a list numbered [1] [2].

    The bug this fixes, found on screen: the citation list is built in order of first
    appearance and rendered from the template's own loop index, so two markers spread
    across five passages produced a two-entry list labelled [1] [2] while the prose
    still said [1] and [4]. The content was right — entry [2] really was passage 4 —
    and the numbering was a lie. A student following [4] found no [4].

    That is the worst shape a citation bug can take here, because it is invisible
    unless you count: the answer looks cited, the source is genuinely the right one,
    and the one thing that does not work is the act of following it.
    """
    from ai_backend.contracts.models import Chunk
    from ai_backend.pipelines.grounding import passages_from, resolve_citations

    chunks = [
        Chunk(
            id=f"c{n}",
            document_id=f"doc{n}",
            content=f"passage {n} body",
            source_location=f"section {n}",
            score=0.9,
        )
        for n in range(1, 6)
    ]
    passages = passages_from(chunks, [])

    text, citations = resolve_citations(
        "The first claim [1]. The fourth claim [4].", passages
    )

    # Two entries, in the order the reader meets them.
    assert len(citations) == 2
    assert citations[0].source_location == "section 1"
    assert citations[1].source_location == "section 4"
    # And the prose now points at those positions rather than at the model's.
    assert text == "The first claim [1]. The fourth claim [2]."


def test_a_marker_outside_the_passages_is_removed_from_the_prose() -> None:
    """A hallucinated [9] leaves no dangling marker behind.

    Dropping it from the list while leaving it in the text is the same defect as
    above from the other direction: a marker a reader can see and cannot follow.
    """
    from ai_backend.contracts.models import Chunk
    from ai_backend.pipelines.grounding import passages_from, resolve_citations

    chunks = [
        Chunk(
            id="c1",
            document_id="doc1",
            content="only passage",
            source_location="section 1",
            score=0.9,
        )
    ]
    text, citations = resolve_citations(
        "A real claim [1]. An invented one [9].", passages_from(chunks, [])
    )

    assert len(citations) == 1
    assert "[9]" not in text
    assert text == "A real claim [1]. An invented one."


def test_two_markers_for_one_passage_collapse_onto_one_number() -> None:
    """Repeating a source does not create a second entry for it."""
    from ai_backend.contracts.models import Chunk
    from ai_backend.pipelines.grounding import passages_from, resolve_citations

    chunks = [
        Chunk(
            id=f"c{n}",
            document_id=f"doc{n}",
            content=f"passage {n}",
            source_location=f"section {n}",
            score=0.9,
        )
        for n in (1, 2)
    ]
    text, citations = resolve_citations(
        "First [2]. Again [2]. Other [1].", passages_from(chunks, [])
    )

    assert len(citations) == 2
    assert citations[0].source_location == "section 2"
    assert text == "First [1]. Again [1]. Other [2]."


def test_renumbering_does_not_reflow_the_rest_of_the_answer() -> None:
    """Tidying a dropped marker must not touch whitespace anywhere else.

    `.answer__text` is `pre-wrap`, so the indentation a model puts on a sub-list or a
    column of figures is load-bearing — it is the whole reason block markdown is not
    parsed. The first version of the cleanup ran `[ \t]{2,}` over the entire answer to
    close the gap a removed marker left, which reflowed every one of those, in answers
    that had no bad marker in them at all.
    """
    from ai_backend.contracts.models import Chunk
    from ai_backend.pipelines.grounding import passages_from, resolve_citations

    chunks = [
        Chunk(
            id="c1",
            document_id="doc1",
            content="terms",
            source_location="section 1",
            score=0.9,
        )
    ]
    original = "Payment terms [1]:\n  - Net 45\n  - Late fee  1.5% monthly"

    text, _ = resolve_citations(original, passages_from(chunks, []))

    assert text == "Payment terms [1]:\n  - Net 45\n  - Late fee  1.5% monthly"
