"""PRD Section 5 — student must-have:

    "I want to hold the demo corpus and my own documents at the same time and switch
    between them, so that I can watch a demonstration on documents whose outcome is
    already measured and then try the same idea on material I actually care about,
    without losing either."

PRD Section 6 acceptance criteria:

    Given both a demo corpus and uploaded documents are indexed, when a student
    switches between them, then only the active one is searched, and a question the
    other corpus answers finds nothing rather than answering from it.

    Given a switch, when the next question is asked, then it is not served from an
    answer cached against the other corpus.

    Given JavaScript is disabled, when the corpus is switched, then it works and the
    choice survives a reload.

Milestone 4.

**Both at once was impossible before this, not merely awkward.** The demo set is
exactly `max_files_per_session` files and the limit was per session, so
`existing + 5 > 5` was true for *any* existing document: one upload permanently blocked
the demo corpus. With no delete route, the only escape was Start over — which also
discards the spend readout, the conversation and every recorded run.

**The scoping assertion is the load-bearing one.** `index_scope` is four lines because
`Retriever.retrieve` and every `VectorStore` method take `session_id` as an opaque
scope string that neither implementation interprets; the whole two-corpus design is
that the callers pass a different string. The first test below is what says that string
actually reaches the index — and if it passes, the rest of the design is sound.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = [
    pytest.mark.story("hold the demo corpus and my own documents"),
    pytest.mark.milestone(4),
]

# Something only the student's own corpus can answer, and something only the demo set
# can. Each is a fact that appears in one corpus and nowhere in the other, so an answer
# citing it is proof of which index was searched.
MINE = b"# Field notes\n\nThe kestrel roosts on the north gable every evening.\n"
MINE_QUESTION = "Where does the kestrel roost?"
DEMO_QUESTION = "When is payment due on a correct invoice?"


async def _upload_mine(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/upload",
        files=[("files", ("field-notes.md", MINE, "text/markdown"))],
        follow_redirects=True,
    )
    assert response.status_code == 200, response.text


async def _both_corpora(client: httpx.AsyncClient) -> None:
    """Load the demo set and upload a document of the student's own.

    In that order, because `/demo-documents` switches the browser to the demo corpus:
    uploading afterwards would put the student's file in the demo corpus too. The upload
    below is preceded by an explicit switch for the same reason it matters in the UI —
    an upload joins the corpus you are looking at.
    """
    assert (await client.post("/demo-documents", follow_redirects=True)).status_code == 200
    await client.post("/corpus", data={"corpus": "mine"}, follow_redirects=False)
    await _upload_mine(client)


# -- the criterion the design rests on ---------------------------------------


async def test_only_the_active_corpus_is_searched(client: httpx.AsyncClient) -> None:
    """**If this passes, the scoping is right.**

    Not "the other corpus ranks lower" — *finds nothing*. A demo-corpus passage
    surfacing under the student's own documents would be worse than a missing answer:
    it would carry citations pointing at files they never uploaded, and every
    measurement on the Why-agentic page would silently be a measurement of the wrong
    corpus.
    """
    await _both_corpora(client)

    # Asserted on the **citation**, not on the answer text, and the difference matters:
    # the page echoes the question in the run's header, so a question containing a word
    # from the other corpus would make a text search report a leak that is not one. A
    # citation names the document retrieval actually reached, which is the fact in
    # question.
    #
    # Active: the student's own. The demo corpus is still indexed and must be
    # unreachable anyway.
    answer = (
        await client.post(
            "/ask/fragment",
            data={"question": DEMO_QUESTION, "strategy": "naive_rag"},
        )
    ).text
    assert "acme-" not in answer.lower(), (
        "a question about the demo corpus was answered from it, citations and all, "
        "while the student's own documents were the active corpus"
    )

    # And the other way: the student's own fact is unreachable from the demo corpus.
    await client.post("/corpus", data={"corpus": "demo"}, follow_redirects=False)
    answer = (
        await client.post(
            "/ask/fragment",
            data={"question": MINE_QUESTION, "strategy": "naive_rag"},
        )
    ).text
    assert "field-notes" not in answer, (
        "a document from the student's own corpus was cited by a run against the demo "
        "corpus"
    )
    assert "could not find anything relevant" in answer, (
        "the run found *something* for a question only the other corpus answers — the "
        "honest outcome here is a refusal, not a near miss"
    )


async def test_both_corpora_are_held_at_once(client: httpx.AsyncClient) -> None:
    """Neither refuses the other, and switching back finds everything as it was.

    The failure this replaces: the demo set is exactly the file limit, so a per-session
    count made any upload block it permanently — and the demo set, loaded first, made
    every upload fail. One of the two was always unavailable.
    """
    await _both_corpora(client)

    mine = (await client.get("/")).text
    assert "field-notes.md" in mine
    assert "acme" not in mine.lower(), (
        "the document list shows files the active index cannot reach"
    )

    await client.post("/corpus", data={"corpus": "demo"}, follow_redirects=False)
    demo = (await client.get("/")).text
    assert "acme" in demo.lower(), "the demo corpus was lost when the student uploaded"
    assert "field-notes.md" not in demo

    # And the rail reports both counts side by side, which is what says "held at once"
    # to a person rather than to a test.
    assert "Demo corpus" in demo and "My documents" in demo


async def test_a_full_corpus_does_not_block_the_other(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """The limit is per corpus, which is what makes holding both possible at all."""
    session_id = str(session["session_id"])
    files = [("files", (f"note-{n}.md", b"# Note\n\nSomething.\n", "text/markdown"))
             for n in range(5)]
    filled = await client.post(
        f"/api/v1/sessions/{session_id}/documents",
        files=files,
        data={"corpus": "mine"},
        headers=auth,
    )
    assert filled.status_code == 200, filled.text

    # A sixth into the same corpus is still refused, whole.
    sixth = await client.post(
        f"/api/v1/sessions/{session_id}/documents",
        files=[("files", ("note-6.md", b"# Note\n", "text/markdown"))],
        data={"corpus": "mine"},
        headers=auth,
    )
    assert sixth.status_code == 413, sixth.text

    # The demo corpus is untouched by that, and still loads.
    demo = await client.post(
        f"/api/v1/sessions/{session_id}/documents/demo", headers=auth
    )
    assert demo.status_code == 200, demo.text
    assert demo.json()["accepted"] >= 1


async def test_clearing_one_corpus_leaves_the_other_intact(
    client: httpx.AsyncClient,
) -> None:
    """The missing half of the limit, and why Start over stopped being the only escape.

    `DELETE /sessions/{id}` frees vectors but not `document` rows, so it could never be
    reused to clear a corpus — the rows would survive, keep counting against the limit,
    and list files whose chunks were gone.
    """
    await _both_corpora(client)

    await client.post("/corpus/clear", data={"corpus": "mine"}, follow_redirects=True)

    mine = (await client.get("/")).text
    assert "field-notes.md" not in mine, "the cleared corpus still lists its documents"

    await client.post("/corpus", data={"corpus": "demo"}, follow_redirects=False)
    demo = (await client.get("/")).text
    assert "acme" in demo.lower(), "clearing one corpus took the other with it"


# -- the cache does not cross the boundary -----------------------------------


async def test_an_answer_cached_against_one_corpus_is_not_served_to_the_other(
    client: httpx.AsyncClient,
) -> None:
    """A cached answer is an answer *about a particular corpus*.

    Serving one across the boundary would hand a student an answer with citations
    pointing at documents the active index does not hold — the same failure as
    retrieving across it, one layer up and harder to notice, because the citations
    would look real.

    Entries are keyed by scope rather than by session, so this is correct by
    construction: the other corpus's answers were never reachable. That is worth
    asserting precisely *because* it needs no invalidation — an implementation that
    keyed on the session would pass every other test in this file.
    """
    await _both_corpora(client)

    # Ask on the demo corpus, so an answer is cached against it.
    await client.post("/corpus", data={"corpus": "demo"}, follow_redirects=False)
    await client.post(
        "/ask/fragment", data={"question": DEMO_QUESTION, "strategy": "agentic_rag"}
    )

    # The identical question against the student's own documents must not be answered
    # from that entry.
    await client.post("/corpus", data={"corpus": "mine"}, follow_redirects=False)
    page = (
        await client.post(
            "/ask/fragment",
            data={"question": DEMO_QUESTION, "strategy": "agentic_rag"},
        )
    ).text

    assert "acme" not in page.lower(), (
        "the same question was served the other corpus's cached answer, citations and "
        "all"
    )


# -- without JavaScript ------------------------------------------------------


async def test_the_switch_works_with_no_javascript(client: httpx.AsyncClient) -> None:
    """A form post and a redirect, and the choice survives a reload.

    The hard requirement in CLAUDE.md, and the one control where it is least optional:
    the corpus decides what every other control on the page is acting on, so a corpus
    toggle that needed a script would leave a scripts-disabled browser permanently
    looking at one corpus with no way to say so.
    """
    page = (await client.get("/")).text
    assert 'action="/corpus"' in page and 'method="post"' in page

    response = await client.post(
        "/corpus", data={"corpus": "demo"}, follow_redirects=False
    )
    assert response.status_code == 303, response.text
    assert "axis_corpus" in response.headers.get("set-cookie", "")

    # Survives a reload, because it is a cookie rather than a query parameter — and
    # reads back as the *selected* one on a page the switch did not come from.
    for path in ("/", "/compare", "/trace", "/why-agentic", "/summarize"):
        reloaded = (await client.get(path)).text
        assert 'value="demo"' in reloaded and 'aria-pressed="true"' in reloaded, (
            f"{path} lost the corpus selection"
        )


async def test_an_unknown_corpus_falls_back_to_the_empty_one(
    client: httpx.AsyncClient,
) -> None:
    """A cookie is user-editable and this one names an index scope.

    The harm from an arbitrary name is nil — the scope would be empty — but "nothing
    can name a scope we did not define" is cheaper to hold than to reason about later.
    The fallback is `mine` rather than `demo` deliberately: an unrecognised value should
    land on the corpus that is empty until a student fills it, not on one holding five
    documents they did not choose.
    """
    await client.post("/corpus", data={"corpus": "demo"}, follow_redirects=False)
    response = await client.post(
        "/corpus", data={"corpus": "../../etc"}, follow_redirects=False
    )

    assert response.status_code == 303
    assert "axis_corpus=mine" in response.headers.get("set-cookie", "")
