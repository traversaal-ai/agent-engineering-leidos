"""PRD Section 5 — student must-have:

    "I want a summarizer mode so that I can get a structured overview of my documents
    without having to ask a specific question first."

PRD Section 6 acceptance criteria:

    Given at least one indexed document, when a student asks for a summary without
    having asked any question, then a structured overview is produced, and each
    section cites the document and location it came from.

    Given a summary is requested, when the session's cost cap is already reached,
    then it is refused before any LLM call is made.

    Given no documents are indexed, when a summary is requested, then it says so
    rather than returning an empty overview.

    Given a summary has been produced, when the student looks at the trace, then the
    per-document and combining steps appear separately, so the map-reduce shape and
    where its cost went are both visible.

Milestone 3.

**The cap criterion is the one with teeth**, and it is stricter here than for a query.
Summarization's cost scales with how much the student uploaded rather than with what
they asked, so it is the most expensive single action available after Compare and the
one a student is most likely to press repeatedly while exploring. `call_count == 0` is
the assertion, because a refusal message proves nothing about whether a provider was
paid before it was written.

**The trace criterion is not decoration.** Summarizer mode's teaching job is a
contrast: summarizing reads everything and scales with the corpus, retrieval reads the
relevant part and scales with the question. That contrast is only legible if the trace
shows one step per document — a single collapsed step would show the total cost while
hiding what it scales with, which is the entire point.
"""

from __future__ import annotations

import re

import httpx
import pytest

from ai_backend.contracts.models import StepType
from ai_backend.summarize import EMPTY_SUMMARY, NOTHING_SELECTED
from tests.docfixtures import make_pdf

pytestmark = [
    pytest.mark.story("summarizer mode"),
    pytest.mark.milestone(3),
]

_HANDBOOK = (
    "Parental leave. Employees are entitled to 16 weeks of fully paid parental "
    "leave. Remote work is permitted up to three days each week."
)
_SECURITY = (
    "Access reviews. Every production system is subject to a quarterly access "
    "review, owned by the named service owner. Full-disk encryption is mandatory."
)


async def _index(client: httpx.AsyncClient, session_id: str, auth: dict[str, str]) -> None:
    await client.post(
        f"/api/v1/sessions/{session_id}/documents",
        files=[
            ("files", ("handbook.pdf", make_pdf(_HANDBOOK), "application/pdf")),
            ("files", ("security.pdf", make_pdf(_SECURITY), "application/pdf")),
        ],
        headers=auth,
    )


async def test_a_summary_is_produced_without_any_question_being_asked(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """"without having to ask a specific question first" — the whole point.

    This is the post-upload on-ramp: before it, a student who had just indexed
    documents had to invent a question before anything happened at all.
    """
    session_id = str(session["session_id"])
    await _index(client, session_id, auth)

    response = await client.post(
        f"/api/v1/sessions/{session_id}/summarize", headers=auth
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"].strip()
    assert body["summary"] != EMPTY_SUMMARY
    assert body["documents"] == 2, body


async def test_each_document_is_cited_by_name(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """"each section cites the document and location it came from".

    By filename, not by id. The names live in the Backend's `document` table and are
    passed down, because a summary referring to documents by uuid would be unreadable
    — and the AI Backend holding a second copy of them is the drift System Design
    Section 7 keeps out.
    """
    session_id = str(session["session_id"])
    await _index(client, session_id, auth)

    body = (
        await client.post(f"/api/v1/sessions/{session_id}/summarize", headers=auth)
    ).json()

    filenames = {c["filename"] for c in body["citations"]}
    assert filenames == {"handbook.pdf", "security.pdf"}, body["citations"]
    assert all(c["document_id"] for c in body["citations"])
    assert all(c["kind"] == "document" for c in body["citations"])


async def test_the_api_reads_only_the_documents_it_was_given(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """The selection is enforced at the API, not only by the page that offers it.

    A bare POST still means everything — that is what it meant before there was a
    choice, and the two tests above rely on it — so the filter has to be the presence
    of `document_ids` rather than its truthiness.
    """
    session_id = str(session["session_id"])
    await _index(client, session_id, auth)

    everything = (
        await client.post(f"/api/v1/sessions/{session_id}/summarize", headers=auth)
    ).json()
    handbook = next(
        c["document_id"] for c in everything["citations"] if c["filename"] == "handbook.pdf"
    )

    body = (
        await client.post(
            f"/api/v1/sessions/{session_id}/summarize",
            headers=auth,
            json={"document_ids": [handbook]},
        )
    ).json()

    assert body["documents"] == 1, body
    assert {c["filename"] for c in body["citations"]} == {"handbook.pdf"}, (
        body["citations"]
    )


async def test_an_empty_selection_costs_nothing_at_the_api_too(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str], fake_llm
) -> None:
    """`[]` is a request for nothing, and must not be read as a request for everything.

    The Frontend catches this before a round trip, but the rule has to hold here: this
    is where it holds for *any* caller, and the reading it rules out — no documents named
    means read them all — would make the most expensive action Axis offers the default
    outcome of a malformed request.
    """
    session_id = str(session["session_id"])
    await _index(client, session_id, auth)
    before = fake_llm.call_count

    response = await client.post(
        f"/api/v1/sessions/{session_id}/summarize",
        headers=auth,
        json={"document_ids": []},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"] == NOTHING_SELECTED, body["summary"]
    assert body["documents"] == 0
    assert body["cost_usd"] == 0.0
    assert fake_llm.call_count == before, "an empty selection reached a provider"


async def test_an_empty_session_says_so_and_makes_no_llm_call(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str], fake_llm
) -> None:
    """"it says so rather than returning an empty overview".

    And it costs nothing. Asking a model to summarise nothing produces a confident
    description of an empty set — the same failure as answering a question from no
    context, which both query pipelines already refuse for the same reason.
    """
    session_id = str(session["session_id"])
    before = fake_llm.call_count

    response = await client.post(
        f"/api/v1/sessions/{session_id}/summarize", headers=auth
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"] == EMPTY_SUMMARY
    assert body["documents"] == 0
    assert body["cost_usd"] == 0.0
    assert fake_llm.call_count == before, "a model was called to summarise nothing"


async def test_a_capped_session_is_refused_before_any_llm_call(
    client: httpx.AsyncClient,
    session: dict,
    auth: dict[str, str],
    fake_llm,
    spend_to_cap,
) -> None:
    """The cap criterion, and it matters more here than for a query.

    Summarization's cost scales with the corpus rather than with the question, so it
    is the most expensive action available after Compare. `call_count` is the
    assertion: a refusal message is not evidence that nothing was paid for before it
    was written.
    """
    session_id = str(session["session_id"])
    await _index(client, session_id, auth)
    before = fake_llm.call_count

    spend_to_cap(session_id)

    response = await client.post(
        f"/api/v1/sessions/{session_id}/summarize", headers=auth
    )

    assert response.status_code == 429, response.text
    assert fake_llm.call_count == before, "a model was called after the cap was reached"


async def test_the_trace_shows_one_step_per_document_and_one_that_combines(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """"the per-document and combining steps appear separately".

    The map-reduce shape has to be visible, because that shape *is* the lesson: cost
    grows with the number of documents. One collapsed step would report the total
    while hiding what the total scales with.
    """
    session_id = str(session["session_id"])
    await _index(client, session_id, auth)

    await client.post(f"/api/v1/sessions/{session_id}/summarize", headers=auth)

    steps = (
        await client.get(
            f"/api/v1/sessions/{session_id}/trace/steps", headers=auth
        )
    ).json()
    summarize_steps = [
        s for s in steps if s["step_type"] == StepType.SUMMARIZE.value
    ]

    per_document = [
        s for s in summarize_steps if (s.get("attributes") or {}).get("document_id")
    ]
    combining = [
        s for s in summarize_steps if (s.get("attributes") or {}).get("combining")
    ]

    assert len(per_document) == 2, summarize_steps
    assert len(combining) == 1, summarize_steps
    # Each per-document step carries its own cost, which is what makes "this scales
    # with the corpus" readable off the trace rather than asserted in prose.
    assert all(s["cost_usd"] > 0 for s in per_document), per_document


async def test_a_partial_summary_says_how_much_it_left_out(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """Summarizing N documents needs N+1 LLM calls, against a *per-query* bound.

    So a session with more documents than the bound allows must degrade rather than
    fail: `max_llm_calls_per_query` scales with the query and summarization scales
    with the corpus, which is exactly the contrast the mode exists to teach — and it
    means the bound will genuinely be reached.

    The requirement is not merely "do not crash". A summary that silently covered
    three of five documents would be *worse* than a refusal, because a student would
    read it as a description of everything they uploaded. So it must say what it left
    out, and still combine what it read.
    """
    session_id = str(session["session_id"])
    # Four documents against the test settings' `max_llm_calls_per_query` of 4: four
    # map calls plus one combine is five, so at least one document cannot be read.
    await client.post(f"/api/v1/sessions/{session_id}/documents/demo", headers=auth)

    # Named, because the demo set loads into the `demo` corpus and a bare POST reads the
    # default one. That is the point of the corpus rather than an inconvenience: a
    # summary is meant to scale with the corpus in front of you, so reading both would
    # report a cost for documents the student is not looking at.
    response = await client.post(
        f"/api/v1/sessions/{session_id}/summarize",
        headers=auth,
        json={"corpus": "demo"},
    )

    assert response.status_code == 200, response.text
    body = response.json()

    # Something was produced, from fewer than all four documents.
    assert body["documents"] >= 1, body
    assert body["documents"] < 4, "expected the per-query LLM bound to be reached"
    assert "not read" in body["summary"], (
        f"a partial summary must say what it omitted: {body['summary']!r}"
    )
    # And the combining step still ran — the map loop holds a call back for it, so a
    # run never pays for N summaries and then fails to join them.
    steps = (
        await client.get(
            f"/api/v1/sessions/{session_id}/trace/steps", headers=auth
        )
    ).json()
    combining = [
        s
        for s in steps
        if s["step_type"] == StepType.SUMMARIZE.value
        and (s.get("attributes") or {}).get("combining")
    ]
    assert len(combining) == 1, "the reserved combining call never happened"
    assert combining[0]["attributes"]["documents_skipped"] >= 1


async def test_summarizing_is_not_a_strategy(client: httpx.AsyncClient) -> None:
    """It sits on neither axis, so it must not be in the `Strategy` enum.

    Putting it there would make Compare's one variable stop meaning orchestration — and
    `AgentStep.strategy` is persisted in SQLite, so the vocabulary is not cheap to
    change back.
    """
    from ai_backend.contracts.models import Strategy

    assert "summar" not in " ".join(s.value for s in Strategy).lower()


def _checkboxes(page: str) -> list[tuple[str, bool]]:
    """The document picker as `(document_id, checked)`, in the order it renders."""
    return [
        (m.group("id"), "checked" in m.group("rest"))
        for m in re.finditer(
            r'<input type="checkbox" name="documents" value="(?P<id>[^"]+)"'
            r'(?P<rest>[^>]*)>',
            page,
        )
    ]


async def _indexed_via_the_frontend(client: httpx.AsyncClient) -> list[str]:
    """A session with the demo corpus, through the pages a student uses.

    The client's own cookie jar carries the session across these calls, exactly as a
    browser would. Passing `cookies=` per request instead *replaces* the jar rather
    than merging with it, which silently mints a fresh empty session — and a test would
    then pass against a session holding no documents at all.
    """
    await client.post("/demo-documents", follow_redirects=True)
    return [doc for doc, _ in _checkboxes((await client.get("/summarize")).text)]


async def test_the_summarize_action_works_with_no_javascript(
    client: httpx.AsyncClient,
) -> None:
    """A plain form post, per CLAUDE.md's hard requirement.

    Checkboxes and a submit button, and nothing else — `axis.js` is never loaded here,
    so this exercises the server-rendered path exactly as a scripts-disabled browser
    would. The one control in Axis that spends money should not need a script to work.
    """
    documents = await _indexed_via_the_frontend(client)
    assert documents, "the summarize page offered no documents to choose"

    page = (await client.get("/summarize")).text
    assert 'action="/summarize"' in page, "the summarize action is not offered"

    response = await client.post("/summarize", data={"documents": documents})

    assert response.status_code == 200, response.text
    # The overview rendered server-side, not an empty page.
    assert "Summarize documents" in response.text
    assert EMPTY_SUMMARY not in response.text, (
        "the summary ran against a session holding no documents"
    )


async def test_only_the_chosen_documents_are_read(
    client: httpx.AsyncClient,
) -> None:
    """The point of the picker.

    Summarizing is the *contrast* that justifies retrieval — read everything, or read
    the relevant part — and picking documents is what makes its cost curve measurable
    rather than asserted: one document, then four, and the price moves with the corpus
    in a way asking a question never does.

    So the assertion is on both halves. The overview covers exactly what was picked,
    and it cites only those documents — a summary that quietly read more than it was
    asked to would report a cost the student cannot account for.
    """
    documents = await _indexed_via_the_frontend(client)
    assert len(documents) >= 2, "need more than one document to prove selection"

    one = (await client.post("/summarize", data={"documents": documents[:1]})).text
    two = (await client.post("/summarize", data={"documents": documents[:2]})).text

    assert "1 document read" in one, one[:400]
    assert "2 documents read" in two, two[:400]


async def test_an_empty_selection_is_refused_without_an_llm_call(
    client: httpx.AsyncClient, fake_llm
) -> None:
    """Unchecking everything must not mean "read everything".

    The other reading would make a request that named no documents run the most
    expensive action available over the whole corpus — the wrong way round for the one
    operation whose cost scales with the upload, and reachable by a stale page posting
    an old form. Caught in the Frontend, so it does not even cost a round trip.
    """
    await _indexed_via_the_frontend(client)
    before = fake_llm.call_count

    response = await client.post("/summarize", data={})

    assert response.status_code == 200
    assert "Select at least one document" in response.text
    assert fake_llm.call_count == before, (
        "an empty selection reached a provider — summarizing on an empty selection "
        "must cost nothing"
    )


async def test_the_summary_survives_a_visit_to_another_page(
    client: httpx.AsyncClient, fake_llm
) -> None:
    """Summarize is a page in the nav now, so it can be navigated back to.

    Before it was a button whose result existed only in the response to pressing it, so
    a student who opened the trace to show the map-reduce steps lost the summary they
    went there to explain. Recomputing on the way back would charge for a navigation —
    on the one action expensive enough for that to show in the spend readout.
    """
    documents = await _indexed_via_the_frontend(client)
    await client.post("/summarize", data={"documents": documents[:1]})
    after_run = fake_llm.call_count

    await client.get("/trace")
    back = await client.get("/summarize")

    assert "1 document read" in back.text, "the summary was lost on the way back"
    assert fake_llm.call_count == after_run, "coming back re-ran the summary"
    # And the selection that produced it, so what is on screen is attributable.
    checked = [doc for doc, on in _checkboxes(back.text) if on]
    assert checked == documents[:1], checked


async def test_a_document_that_failed_to_index_cannot_be_chosen(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """Shown, and disabled. It has no chunks, so there is nothing to read.

    Hiding it would be worse: a student uploaded it, and a document that vanishes from
    the one page that lists what can be read reads as a bug rather than as a failure
    they can act on.
    """
    await client.post(
        f"/api/v1/sessions/{session['session_id']}/documents",
        files=[("files", ("broken.pdf", b"not a pdf at all", "application/pdf"))],
        headers=auth,
    )
    client.cookies.update(
        {"axis_session": session["session_id"], "axis_token": session["token"]}
    )

    page = (await client.get("/summarize")).text

    assert "broken.pdf" in page, "a failed document is missing from the picker"
    assert "docpick--off" in page, "a failed document is offered as summarizable"
