"""PRD Section 5 — student must-have:

    "I want a follow-up question to be understood in the light of what I already
    asked, and to see that the baseline cannot do this, so that I understand what
    conversational memory is and where it stops."

PRD Section 6 acceptance criteria:

    Given a question has been answered, when a follow-up referring to it is asked of
    the agentic strategy, then the follow-up is resolved into a standalone question
    before retrieval, and both the question as typed and the question as resolved
    are shown.

    Given the same follow-up is asked of the baseline, when it runs, then it is
    retrieved for as typed and the conversation is not consulted.

    Given a resolved follow-up, when its answer is returned, then every claim in it
    is still cited to a passage; nothing is answered from the conversation itself.

    Given a student starts a new conversation, when they do so, then the turns are
    forgotten and the indexed documents are not.

Milestone 4.

**The narrowness is the teaching point, not a shortfall.** Axis's memory resolves
*references*; it does not carry *facts*. The course material's own example is the
fact-carrying kind — "Alice has a parrot", then "Bob has two cats", then "how many
pets?" — and Axis declines it, because a fact recalled from a conversation has no
passage to cite and Section 6's citation criterion forbids exactly that answer. So
history reaches the rewriter's prompt and nothing else, which is enforced
structurally rather than by instruction. `docs/Axis_Notebook_Alignment.md` §9 records
it at length because a student who read the material *will* ask.

**What is asserted offline, and what is not.** That the history reaches the
rewriter, that the baseline never sees it, and that the turns are forgotten on
request — all real and all checkable. Whether the resolution is *correct* is not:
the offline stand-in echoes the question rather than resolving it, so a live
resolution needs a real provider. The resolution *ceiling*
(`--compare-strategies`) is what measures the mechanism offline, and it is what the
Why-agentic page quotes.
"""

from __future__ import annotations

import httpx
import pytest

from ai_backend.contracts.models import StepType
from tests.docfixtures import make_pdf

pytestmark = [
    pytest.mark.story("follow-up question"),
    pytest.mark.milestone(4),
]

_MSA = (
    "Master services agreement. Agreement number MSA-2026-0417. Effective date "
    "1 March 2026. Term: three years, expiring 28 February 2029. Payment is due "
    "Net 45 from receipt of a correct invoice."
)

_FIRST = "When did the master services agreement take effect?"
# Meaningless on its own, which is the entire point: every word in it is common and
# the thing it refers to is in the turn before.
_FOLLOW_UP = "How long is it?"


async def _index(client: httpx.AsyncClient, session_id: str, auth: dict[str, str]) -> None:
    response = await client.post(
        f"/api/v1/sessions/{session_id}/documents",
        files=[("files", ("msa.pdf", make_pdf(_MSA), "application/pdf"))],
        headers=auth,
    )
    assert response.status_code == 200, response.text


async def _ask(
    client: httpx.AsyncClient,
    session_id: str,
    auth: dict[str, str],
    question: str,
    *,
    strategy: str = "agentic_rag",
) -> dict:
    response = await client.post(
        f"/api/v1/sessions/{session_id}/query",
        json={"question": question, "strategy": strategy, "cache": False},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _rewrites(step_store) -> list:
    return [s for s in step_store.all_steps if s.step_type is StepType.REWRITE]


async def test_a_follow_up_is_resolved_before_anything_is_searched_for(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str], step_store
) -> None:
    """The criterion: the conversation reaches the question before retrieval does.

    Asserted as "the rewriter was given the turn", not as "the resolution was
    right" — the offline stand-in echoes rather than resolves, and what measures the
    resolution itself is the ceiling in `--compare-strategies`. What *is* checkable
    here is the wiring, which is the half that silently does not exist if the
    Backend forgets to read the conversation.
    """
    await _index(client, session["session_id"], auth)
    await _ask(client, session["session_id"], auth, _FIRST)
    await _ask(client, session["session_id"], auth, _FOLLOW_UP)

    steps = _rewrites(step_store)
    assert steps, "no rewrite step was emitted at all"

    follow_up = steps[-1]
    assert follow_up.attributes.get("history_turns", 0) >= 1, (
        "the follow-up's rewrite saw no conversation, so the question reached "
        "retrieval as four common words with nothing to resolve them against"
    )
    assert follow_up.attributes.get("original") == _FOLLOW_UP


async def test_both_the_question_as_typed_and_as_resolved_are_recorded(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str], step_store
) -> None:
    """"both the question as typed and the question as resolved are shown".

    Both, because the *mechanism* of this stage is the difference between them. A
    step recording only its output would state an outcome and show nothing — a
    student could not see that "How long is it?" had become anything.
    """
    await _index(client, session["session_id"], auth)
    await _ask(client, session["session_id"], auth, _FIRST)
    await _ask(client, session["session_id"], auth, _FOLLOW_UP)

    step = _rewrites(step_store)[-1]
    assert step.attributes.get("original"), "the question as typed is not recorded"
    assert step.attributes.get("rewritten") is not None, (
        "the question as searched for is not recorded"
    )
    assert "changed" in step.attributes, (
        "nothing says whether the rewrite changed anything, so a card cannot tell "
        "'unchanged' from 'not run'"
    )


async def test_the_baseline_never_remembers(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str], step_store
) -> None:
    """The load-bearing contrast, and the reason this is a story at all.

    Naive RAG is handed the same history and ignores it — the pipeline simply does
    not read `ctx.history`. That is deliberate and structural: filtering it out in
    the Backend instead would move the decision somewhere a student cannot see, and
    a baseline with the comparator's mechanisms is not a baseline.

    Asserted by the *absence* of a rewrite step, which is the same kind of assertion
    as `route` and `decompose` being absent from a naive trace.
    """
    await _index(client, session["session_id"], auth)
    await _ask(client, session["session_id"], auth, _FIRST, strategy="naive_rag")

    before = len(_rewrites(step_store))
    await _ask(client, session["session_id"], auth, _FOLLOW_UP, strategy="naive_rag")

    assert len(_rewrites(step_store)) == before, (
        "the baseline emitted a rewrite step, so it is resolving follow-ups — and a "
        "baseline that can do what the comparator does measures nothing"
    )


async def test_a_resolved_answer_is_still_cited_to_a_passage(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """Memory resolves references; it does not carry facts.

    The distinction this asserts is why Axis declines the course material's own
    memory example. A fact recalled from the conversation has no passage to cite, so
    an answer drawing on one could not satisfy Section 6 — history therefore reaches
    the rewriter's prompt and never the synthesis prompt, and every answer stays
    grounded in something a student can go and read.
    """
    await _index(client, session["session_id"], auth)
    await _ask(client, session["session_id"], auth, _FIRST)
    answer = await _ask(client, session["session_id"], auth, _FOLLOW_UP)

    if answer["grounded"]:
        assert answer["citations"], (
            "a grounded answer to a follow-up carried no citation, so part of it "
            "came from the conversation rather than from a passage"
        )
    else:
        # Refusing is the other correct outcome, and the more likely one offline:
        # the stand-in cannot resolve the pronoun, so retrieval finds nothing and
        # the pipeline declines rather than inventing an answer.
        assert not answer["citations"]


async def test_the_conversation_is_visible_to_the_student(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """The rail's count and the history the rewriter gets are the same number.

    Reported by the Backend rather than counted in the Frontend, because the
    conversation is a *watermark over the runs* — counting runs in the Frontend
    would be right until somebody pressed "New conversation", and then quietly
    wrong.
    """
    await _index(client, session["session_id"], auth)
    session_id = session["session_id"]

    before = await client.get(f"/api/v1/sessions/{session_id}", headers=auth)
    assert before.json()["turn_count"] == 0

    await _ask(client, session_id, auth, _FIRST)

    after = await client.get(f"/api/v1/sessions/{session_id}", headers=auth)
    assert after.json()["turn_count"] == 1


async def test_a_new_conversation_forgets_the_turns_and_keeps_the_documents(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """Three things a student might discard, and these are two different ones.

    `DELETE /sessions/{id}` throws away the index so indexing can be watched again;
    this throws away only what a follow-up can refer to. Conflating them would
    trade the "read any run" story for the memory one — clearing a follow-up chain
    would cost you the corpus and every run on the Trace page.
    """
    await _index(client, session["session_id"], auth)
    session_id = session["session_id"]
    await _ask(client, session_id, auth, _FIRST)

    response = await client.delete(
        f"/api/v1/sessions/{session_id}/turns", headers=auth
    )
    assert response.status_code == 204, response.text

    state = (await client.get(f"/api/v1/sessions/{session_id}", headers=auth)).json()
    assert state["turn_count"] == 0, "the conversation was not forgotten"
    assert state["document_count"] == 1, (
        "starting a new conversation discarded a document; the two are different "
        "things to throw away"
    )


async def test_starting_a_new_conversation_is_idempotent(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """A student who double-clicks should not see an error.

    Same reasoning as `DELETE /sessions/{id}`: a control in front of a class has to
    tolerate being pressed twice.
    """
    session_id = session["session_id"]
    for _ in range(2):
        response = await client.delete(
            f"/api/v1/sessions/{session_id}/turns", headers=auth
        )
        assert response.status_code == 204, response.text


async def test_the_conversation_reset_works_without_javascript(
    client: httpx.AsyncClient, session: dict
) -> None:
    """A form post and a redirect, like every other control in the rail.

    The hard requirement in CLAUDE.md, and the honest choice: nothing in the
    sidebar should need a script to work.
    """
    response = await client.post("/conversation/reset", follow_redirects=False)
    assert response.status_code == 303, response.text
    assert response.headers["location"].startswith("/")
