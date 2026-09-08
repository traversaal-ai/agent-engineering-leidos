"""PRD Section 5 — student must-have:

    "I want a set of example questions labelled with which strategy should win so
    that I can predict the outcome before running it and find out whether I was
    right."

PRD Section 6 acceptance criteria:

    Given the demo document set is indexed, when the question set is offered to a
    student, then each question carries a predicted outcome — which strategy should
    win, or that neither should — and that prediction is one the evaluation harness
    verifies, not one asserted only in the UI.

    Given a question predicted to favour the agentic strategy, when the evaluation
    harness runs, then the mechanism that earned it that prediction measurably
    improves on it over asking the question as written; if it stops doing so, the
    harness fails rather than the label quietly becoming false.

    Given the labelled questions are offered, when a student has uploaded no
    documents, then the questions are not presented as runnable.

    Given JavaScript is disabled, when a labelled question is chosen, then it still
    submits and runs.

Milestone 2.

**The second criterion is the one that matters, and it is not a UI test.** A label
is a prediction, and a prediction nothing checks is decoration that will eventually
be wrong — quietly, in front of a class. So the load-bearing test here asserts that
the measurement behind each `agentic_wins` label still holds, against the ceiling for
the mechanism that earned it: splitting finds a document a blended query misses,
chaining finds one a single hop misses, resolving finds one a bare pronoun misses,
reading everything covers what top-k cannot. If a retrieval change makes the question
as written good enough on its own, that is not a passing state — it means the question
has stopped teaching, and the label has to go or the question has to get harder.

The whole story exists because of the Section 7 risk *"students may conflate
'agentic' or 'graph-based' with 'always better' if demo questions aren't chosen
deliberately"* — and its mirror image, which is what the product actually produced: a
student types the obvious single-fact question first, watches agentic cost three times
as much for the same answer, and concludes orchestration is never worth it.
"""

from __future__ import annotations

import httpx
import pytest

from ai_backend.contracts.models import Strategy
from ai_backend.evaluation.demo import PredictedOutcome, demo_questions, predict
from ai_backend.evaluation.golden import load_golden_set
from ai_backend.evaluation.runner import (
    Ceiling,
    participates,
    run_ceiling,
    run_golden_set,
)

pytestmark = [
    pytest.mark.story("example questions labelled with which strategy should win"),
    pytest.mark.milestone(2),
]


# -- the prediction is real -------------------------------------------------


async def test_an_agentic_wins_label_is_backed_by_a_measured_gain(
    settings,
) -> None:
    """The load-bearing test. A label nothing measures is decoration.

    Asserts that every question labelled `agentic_wins` gains on **the ceiling for
    the mechanism that earned it the label**. Deliberately *not* tolerant of "no
    change": the label predicts a win, and a question that no longer produces one
    has stopped being the question the label describes.

    **This test used to check one ceiling, and that stopped being right.** When
    decomposition was the only mechanism with a ground truth, `agentic_wins` and
    "splitting helps" were the same claim. Now four mechanisms produce the label —
    decomposition, hop chaining, follow-up resolution and full-corpus coverage —
    and checking them all against the decomposition ceiling fails the ones
    decomposition was never going to help. The summarization question caught this:
    labelled `agentic_wins`, correctly, and splitting it changes nothing, also
    correctly, because what answers it is reading every chunk rather than asking
    twice. Verifying the wrong ceiling would have forced the choice between an
    unverified label and a deleted question.
    """
    golden = load_golden_set()
    labelled = [
        q for q in golden.questions if predict(q) is PredictedOutcome.AGENTIC_WINS
    ]
    assert labelled, (
        "No golden question is labelled agentic_wins, so the demo set cannot show a "
        "question where orchestration earns its cost — which is half the comparison."
    )

    baseline = await run_golden_set(
        settings=settings, strategy=Strategy.NAIVE_RAG, golden=golden
    )
    ceilings = {
        which: await run_ceiling(which, settings=settings, golden=golden)
        for which in Ceiling
    }

    def score(result, which: Ceiling) -> float:
        if which is Ceiling.COVERAGE:
            return result.retrieval.coverage
        return result.retrieval.document_recall

    before_by_id = {r.question.id: r for r in baseline.results}

    for question in labelled:
        # The mechanisms this question declares ground truth for. More than one is
        # possible in principle; every one of them has to deliver, since the label
        # does not say which mechanism the win comes from.
        mechanisms = [w for w in Ceiling if participates(question, w)]
        assert mechanisms, (
            f"{question.id!r} is labelled agentic_wins but declares no ground truth "
            f"for any mechanism, so nothing measures the win it promises. Either "
            f"give it `sub_questions`, `hops`, a `resolved` form or "
            f"`expect_full_coverage`, or let it predict a tie."
        )

        for which in mechanisms:
            after_result = next(
                r
                for r in ceilings[which].results
                if r.question.id == question.id
            )
            before = score(before_by_id[question.id], which)
            after = score(after_result, which)
            assert after > before, (
                f"{question.id!r} is labelled agentic_wins on the {which.value} "
                f"ceiling, but {which.mechanism} did not improve it "
                f"({before:.2f} -> {after:.2f}). Either the label is now false, or "
                f"the corpus changed until the question as asked already finds "
                f"everything — in which case it no longer demonstrates the agentic "
                f"win and the set needs a harder one."
            )


async def test_every_offered_question_carries_an_outcome_and_a_reason(
    client: httpx.AsyncClient,
) -> None:
    """"each question carries a predicted outcome", read off the API.

    The reason is asserted alongside the outcome because a prediction without one
    is a spoiler rather than teaching — the student is meant to reason about *why*
    before pressing Ask, not be told the answer.
    """
    response = await client.get("/api/v1/demo/questions")
    assert response.status_code == 200, response.text

    questions = response.json()["questions"]
    assert questions, "the demo question set is empty"

    valid = {o.value for o in PredictedOutcome}
    for entry in questions:
        assert entry["outcome"] in valid, entry
        assert entry["question"].strip(), entry
        assert entry["because"].strip(), entry

    # Both halves of the comparison must be present, or the set teaches one
    # direction only — which is the failure this whole story exists to fix.
    offered = {entry["outcome"] for entry in questions}
    assert PredictedOutcome.AGENTIC_WINS.value in offered, offered
    assert PredictedOutcome.NAIVE_WINS.value in offered, offered


def test_the_question_set_is_derived_rather_than_hand_written() -> None:
    """No outcome is asserted for a question the golden set does not support.

    Guards the mechanism, not the content: every offered question must be a golden
    question, and its label must be the one `predict` derives from that question's
    own declarations. A hand-edited label would pass every other test in this
    module and be exactly the drift the criterion forbids.
    """
    golden = load_golden_set()
    by_id = {q.id: q for q in golden.questions}

    for offered in demo_questions(golden):
        source = by_id.get(offered.id)
        assert source is not None, (
            f"{offered.id!r} is offered to students but is not in the golden set, "
            f"so nothing measures it."
        )
        assert offered.outcome is predict(source), (
            f"{offered.id!r} is offered as {offered.outcome.value!r} but its golden "
            f"declarations imply {predict(source).value!r}."
        )


# -- the demo corpus the labels are about -----------------------------------


async def test_the_demo_corpus_loads_and_becomes_queryable(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """"Given the demo document set is indexed" — the precondition, made reachable.

    Asserted through to chunk counts rather than stopping at HTTP 200: a document
    row that parsed to nothing is indistinguishable from a successful upload in the
    response body, and a labelled question run against an empty index would fail
    for a reason that has nothing to do with the label.
    """
    session_id = str(session["session_id"])

    response = await client.post(
        f"/api/v1/sessions/{session_id}/documents/demo", headers=auth
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["accepted"] >= 2, body
    assert body["rejected"] == 0, body

    listed = (
        await client.get(f"/api/v1/sessions/{session_id}/documents", headers=auth)
    ).json()
    assert listed
    assert all(d["status"] == "ready" for d in listed), listed
    assert sum(d["chunk_count"] for d in listed) > 0, (
        "the demo corpus indexed no chunks, so nothing it claims to answer is "
        "retrievable"
    )


async def test_loading_the_demo_set_respects_the_file_limit(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """The demo corpus has no privileged claim on a student's session.

    Loading it twice would exceed the five-file limit, and the refusal must be the
    same one any other upload gets. The alternative — evicting the student's own
    documents to make room — would be a worse outcome than declining.
    """
    session_id = str(session["session_id"])
    first = await client.post(
        f"/api/v1/sessions/{session_id}/documents/demo", headers=auth
    )
    assert first.status_code == 200, first.text

    second = await client.post(
        f"/api/v1/sessions/{session_id}/documents/demo", headers=auth
    )
    assert second.status_code == 413, second.text
    assert "limit reached" in second.json()["message"].lower()


# -- the no-JavaScript path -------------------------------------------------


async def test_the_questions_are_not_offered_before_anything_is_indexed(
    client: httpx.AsyncClient,
) -> None:
    """"a predicted outcome about a document set nobody indexed is not a prediction".

    A fresh page must not present them as runnable — otherwise a student clicks one
    against an empty index, watches both strategies find nothing, and learns that
    the labels are wrong.
    """
    page = (await client.get("/")).text

    assert "askbar__presets" not in page, (
        "the labelled questions are offered on a page with no documents indexed"
    )
    # The way in is offered instead.
    assert "/demo-documents" in page


async def test_a_labelled_question_runs_with_no_javascript(
    client: httpx.AsyncClient,
) -> None:
    """"Given JavaScript is disabled … it still submits and runs."

    Posts the form the way a browser without scripts would: `preset` carrying the
    pressed button's value, and the textarea empty. `axis.js` is never loaded here,
    so this exercises exactly the fallback path CLAUDE.md makes a hard requirement.
    """
    # Index the corpus first, through the same form action the rail offers.
    #
    # The client's own cookie jar carries the session, exactly as a browser would.
    # Passing `cookies=` per request instead *replaces* the jar rather than merging
    # with it, which silently mints a fresh empty session — and this test would then
    # assert that the questions render against a session holding no documents, which
    # is the one thing the criterion above says must not happen.
    loaded = await client.post("/demo-documents", follow_redirects=False)
    assert loaded.status_code == 303, loaded.text

    page = (await client.get("/")).text
    assert "askbar__presets" in page, (
        "the labelled questions are still not offered after the demo corpus loaded"
    )

    questions = demo_questions()
    chosen = next(q for q in questions if q.outcome is PredictedOutcome.NAIVE_WINS)

    answered = await client.post(
        "/ask",
        data={
            "preset": chosen.question,
            "question": "",
            "strategy": Strategy.NAIVE_RAG.value,
        },
    )
    assert answered.status_code == 200, answered.text
    # The question that ran is the one the button carried, not the empty textarea.
    assert chosen.question[:40] in answered.text
    # And it ran against the indexed corpus: there is an answer block, which the
    # empty textarea path would not have produced. The answer is no longer read out of an expanded Generate card. It is rendered above the pipeline by `_canvas.html`, so what proves a run produced an answer is the answer block itself.
    assert 'data-type="synthesize"' in answered.text
    assert 'class="answer' in answered.text, "the preset question produced no answer"


async def test_an_empty_ask_does_not_500(client: httpx.AsyncClient) -> None:
    """`question` became optional so `preset` could drive the form.

    Which means a genuinely empty submission is now reachable from a client that
    ignores the textarea's `required` attribute. It must render the page, not a 422
    — the browser's own validation is a convenience, never the only check.
    """
    response = await client.post(
        "/ask", data={"question": "", "strategy": Strategy.NAIVE_RAG.value}
    )
    assert response.status_code == 200, response.text
