"""PRD Section 5 — student must-have:

    "I want a reworded repeat of a question I already asked to be answered from a
    cache without a new model call, so that I can see what caching saves and what it
    risks getting wrong."

PRD Section 6 acceptance criteria:

    Given a question has been answered, when a reworded question with the same
    meaning is asked, then the stored answer is returned, no LLM call is made, and
    the page shows the question it matched and how close the match was.

    Given a cache hit, when the answer is shown, then it carries the citations it
    was originally produced with.

    Given a question whose answer depends on when it is asked, when it is submitted,
    then the cache is bypassed in both directions.

    Given a new document is indexed, when a previously cached question is asked
    again, then it is not served from the cache.

    Given a run that was answered from the cache, when it appears in the comparison,
    then the comparison states that and withholds its cost ratio.

    Given the cache is turned off, when the same question is asked twice, then it is
    answered twice at full price.

Milestone 4.

**`call_count` is the assertion that gives this teeth**, exactly as it does for the
cost caps. "The answer came back quickly" proves nothing; "the provider was never
reached" is the claim, and it is only checkable on the fake.

**What is deliberately *not* asserted here: a paraphrase hit.** The whole point of a
*semantic* cache is that "how soon must a correct invoice be paid" matches "when is
payment due on a correct invoice", and `FakeEmbeddingProvider` is a hashed bag of
words that scores that pair at 0.447. Measured, recorded in `ai_backend/agents/cache.py`,
and gated on a real-provider run — the same boundary Section 12 already draws for
answer content. What is asserted offline is the mechanism: a repeat and a reworded
repeat that a bag of words *can* see (punctuation, case, a stopword) both hit, and
everything about the hit is correct.
"""

from __future__ import annotations

import httpx
import pytest

from ai_backend.contracts.models import StepType
from ai_backend.providers.fake import FakeLLMProvider
from tests.docfixtures import make_pdf

pytestmark = [
    pytest.mark.story("reworded repeat of a question"),
    pytest.mark.milestone(4),
]

_MSA = (
    "Payment terms. Invoices are submitted monthly. Payment is due Net 45 from "
    "receipt of a correct invoice. A retainage of five percent is withheld on each "
    "milestone and released upon final acceptance."
)

_QUESTION = "When is payment due on a correct invoice?"
# The same question with the punctuation and case moved, which a bag of words can
# see as identical. A real paraphrase is a real-provider test — see the docstring.
_REWORDED = "when is payment due on a correct invoice"


async def _index(
    client: httpx.AsyncClient, session_id: str, auth: dict[str, str], *, name: str = "msa.pdf"
) -> None:
    await client.post(
        f"/api/v1/sessions/{session_id}/documents",
        files=[("files", (name, make_pdf(_MSA), "application/pdf"))],
        headers=auth,
    )


async def _ask(
    client: httpx.AsyncClient,
    session_id: str,
    auth: dict[str, str],
    question: str,
    *,
    cache: bool = True,
) -> dict:
    response = await client.post(
        f"/api/v1/sessions/{session_id}/query",
        json={"question": question, "strategy": "agentic_rag", "cache": cache},
        headers=auth,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_reworded_repeat_costs_a_resolve_and_nothing_else(
    client: httpx.AsyncClient,
    session: dict,
    auth: dict[str, str],
    fake_llm: FakeLLMProvider,
) -> None:
    """The criterion, and the only assertion that can prove it.

    A refusal to spend is not observable in a response body — the answer looks the
    same either way, which is the point of a cache. So the claim is made against the
    provider: it was very nearly not reached.

    **One call, not none, and the amended criterion says why.** Once a session has
    history, a question has to be *resolved before it can be looked up*: "how long
    is it?" keyed on its own four words would match a previous "how long is it?"
    about something else and serve the wrong answer with citations. So a hit inside a
    conversation costs the resolve — one call instead of four, and no retrieval.
    Keying on the raw question always, as the reference implementation does, would
    make this test pass by being wrong.
    """
    await _index(client, session["session_id"], auth)
    await _ask(client, session["session_id"], auth, _QUESTION)

    before = fake_llm.call_count
    # Three, not four: rewrite, route, synthesize. The decomposer costs a call only
    # when the router says COMPLEX, and the offline router cannot classify — so it
    # correctly falls back to "simple" and never splits. Four is what a real
    # provider costs on a compound question (`test_an_agentic_answer_reports_every_
    # call_it_made`), and the saving below is worth showing at either number.
    assert before >= 3, (
        f"the first answer made {before} LLM calls; an agentic run should cost at "
        f"least three (rewrite, route, synthesize) for the saving to be worth showing"
    )

    second = await _ask(client, session["session_id"], auth, _REWORDED)
    spent = fake_llm.call_count - before

    assert spent <= 1, (
        f"the reworded repeat made {spent} LLM calls; a hit may cost at most the one "
        f"call that resolves the question before looking it up"
    )
    assert second["answer"], "a hit must still return the answer"
    assert second["cost_usd"] < 1.0, "a hit should not be priced like a full run"


async def test_a_cache_hit_keeps_the_citations_it_was_produced_with(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """A cached answer with no provenance is worse than a slow one.

    PRD Section 6 requires every answer to carry a citation, and "it was cached" is
    not an exemption. The reference implementation this was ported from stores only
    the answer string, which makes a hit structurally incapable of satisfying that —
    recorded in `Axis_Notebook_Alignment.md` §9 as one of the four flaws fixed
    rather than inherited.
    """
    await _index(client, session["session_id"], auth)
    first = await _ask(client, session["session_id"], auth, _QUESTION)
    assert first["citations"], "the first answer should be cited"

    second = await _ask(client, session["session_id"], auth, _REWORDED)

    assert second["citations"], "a cache hit came back with no citations at all"
    assert [c["source_location"] for c in second["citations"]] == [
        c["source_location"] for c in first["citations"]
    ], "a hit must carry the citations the stored answer was produced with"


async def test_the_hit_says_what_it_matched_and_how_closely(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str], step_store
) -> None:
    """"the page shows the question it matched and how close the match was".

    Read off the trace rather than the response, because that is where the canvas
    reads it. A cache that cannot show its own reasoning is a black box in a tool
    whose entire claim is that the numbers are real — and the similarity beside the
    threshold is what lets a student see *why* it matched and disagree.
    """
    await _index(client, session["session_id"], auth)
    await _ask(client, session["session_id"], auth, _QUESTION)
    await _ask(client, session["session_id"], auth, _REWORDED)

    lookups = [
        s for s in step_store.all_steps if s.step_type is StepType.CACHE_LOOKUP
    ]
    assert lookups, "no cache lookup was traced at all"

    hit = lookups[-1]
    assert hit.attributes.get("hit") is True, hit.attributes
    assert hit.attributes.get("matched_question") == _QUESTION
    assert hit.attributes.get("similarity") is not None
    assert hit.attributes.get("threshold") is not None, (
        "the similarity is meaningless without the line it was compared against"
    )


async def test_a_hit_skips_the_pipeline_rather_than_shortening_it(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str], step_store
) -> None:
    """The absence of the answering steps is the lesson.

    Load-bearing in exactly the way the absence of `route` and `decompose` is on a
    naive run: the question did not *enter* the pipeline. This is also what the
    canvas draws — the band lights and the track behind it greys out — and a hit
    that emitted a `retrieve` step would make that drawing a lie.
    """
    await _index(client, session["session_id"], auth)
    await _ask(client, session["session_id"], auth, _QUESTION)

    first_run = {s.trace_id for s in step_store.all_steps}
    await _ask(client, session["session_id"], auth, _REWORDED)

    hit_steps = [s for s in step_store.all_steps if s.trace_id not in first_run]
    kinds = {s.step_type for s in hit_steps}

    assert StepType.CACHE_LOOKUP in kinds
    for absent in (
        StepType.ROUTE,
        StepType.DECOMPOSE,
        StepType.RETRIEVE,
        StepType.AUGMENT,
        StepType.SYNTHESIZE,
    ):
        assert absent not in kinds, (
            f"a cache hit emitted a {absent.value!r} step, so the canvas would draw "
            f"a stage that did not run"
        )


async def test_a_time_sensitive_question_is_never_cached(
    client: httpx.AsyncClient,
    session: dict,
    auth: dict[str, str],
    fake_llm: FakeLLMProvider,
) -> None:
    """Bypassed in *both* directions, which is the half that is easy to miss.

    Not storing is as important as not serving: a question about today's share price
    answered once would otherwise be answered with last week's figure for as long as
    the session lived. A cache with no staleness policy is the version of this
    feature that teaches the wrong lesson.
    """
    await _index(client, session["session_id"], auth)
    stale = "What was ACME's share price today?"

    await _ask(client, session["session_id"], auth, stale)
    before = fake_llm.call_count
    await _ask(client, session["session_id"], auth, stale)

    assert fake_llm.call_count > before, (
        "a time-sensitive question was served from the cache; its answer goes out "
        "of date, which is exactly what the keyword gate exists to prevent"
    )


async def test_indexing_a_document_invalidates_what_was_cached(
    client: httpx.AsyncClient,
    session: dict,
    auth: dict[str, str],
    fake_llm: FakeLLMProvider,
) -> None:
    """A cached answer is an answer about a *particular* corpus.

    Once another document is indexed the same question may have a different right
    answer, and serving the stored one would be the cache actively making the system
    wrong — a worse failure than the cost it saves, because it is invisible.
    """
    await _index(client, session["session_id"], auth)
    await _ask(client, session["session_id"], auth, _QUESTION)

    await _index(client, session["session_id"], auth, name="sow.pdf")

    before = fake_llm.call_count
    await _ask(client, session["session_id"], auth, _QUESTION)

    assert fake_llm.call_count > before, (
        "the question was still served from the cache after a new document was "
        "indexed, so the answer describes a corpus that no longer exists"
    )


async def test_the_cache_can_be_switched_off_and_then_costs_full_price(
    client: httpx.AsyncClient,
    session: dict,
    auth: dict[str, str],
    fake_llm: FakeLLMProvider,
) -> None:
    """An instructor has to be able to show the bill.

    The toggle exists for the opposite reason to the web-search one: not to permit
    something risky, but to *decline* a saving, so what the cache was saving can be
    demonstrated rather than asserted.
    """
    await _index(client, session["session_id"], auth)
    await _ask(client, session["session_id"], auth, _QUESTION, cache=False)

    before = fake_llm.call_count
    await _ask(client, session["session_id"], auth, _QUESTION, cache=False)

    assert fake_llm.call_count > before, (
        "the same question was answered from the cache with caching switched off"
    )


async def test_the_baseline_has_no_cache(
    client: httpx.AsyncClient,
    session: dict,
    auth: dict[str, str],
    fake_llm: FakeLLMProvider,
) -> None:
    """Naive RAG pays full price every time, and that is what makes it a baseline.

    A baseline that quietly acquired the comparator's mechanisms would make every
    measurement on the Why-agentic page meaningless — the same reasoning that keeps
    it away from the web route and from conversation history.
    """
    await _index(client, session["session_id"], auth)
    for _ in range(2):
        response = await client.post(
            f"/api/v1/sessions/{session['session_id']}/query",
            json={"question": _QUESTION, "strategy": "naive_rag"},
            headers=auth,
        )
        assert response.status_code == 200, response.text

    before = fake_llm.call_count
    response = await client.post(
        f"/api/v1/sessions/{session['session_id']}/query",
        json={"question": _QUESTION, "strategy": "naive_rag"},
        headers=auth,
    )
    assert response.status_code == 200
    assert fake_llm.call_count > before, (
        "the baseline answered a repeated question without an LLM call, so it has a "
        "cache — and a baseline with the comparator's mechanisms is not a baseline"
    )
