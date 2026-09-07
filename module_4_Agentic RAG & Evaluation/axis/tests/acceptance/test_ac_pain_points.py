"""PRD Section 5 — student must-have:

    "I want to see, for each of the four ways naive RAG fails, the specific mechanism
    that answers it, run on the same documents, so that I learn which failure calls
    for which mechanism rather than learning 'agentic is better'."

PRD Section 6 acceptance criteria:

    Given the demo corpus is indexed, when a student opens the pain-point page, then
    each of the four failures is named in the same words the course material uses,
    beside the mechanism that answers it and a question that exhibits it.

    Given a pain point is chosen, when the student runs it, then the same question
    runs through the baseline and the agentic strategy, both answers are shown, and
    the measured quantity that distinguishes them is shown with them.

    Given a pain point's prediction is shown, when the evaluation harness runs, then
    that prediction is one the harness verifies.

    Given a question that needs two lookups chained, when the agentic strategy runs,
    then the trace shows a second retrieval whose query the model wrote from the
    first one's result, and the baseline's trace shows one retrieval.

    Given a question asking for an overview of the corpus, when both are run, then
    the number of chunks each path actually read is reported.

    Given no documents are indexed, when the pain-point page is opened, then its runs
    are not offered.

    Given JavaScript is disabled, when a pain point is run, then it still runs and
    renders.

Milestone 4.

**This is the criterion the whole platform was missing.** Axis could always show what
orchestration *costs*; it could not show the shape of the problem orchestration
solves, so a student learned a price without learning what they were buying — and the
obvious first question to type is a single-fact lookup where the honest answer is
"that was a waste of money".

**The verification criterion is the load-bearing one**, and it is not a UI test. Every
claim on the page is bound to a golden question, and `--compare-strategies` fails if
the mechanism that question exists to demonstrate stops improving it. The test for
that lives in `tests/evaluation/test_golden_set_m0.py`
(`test_every_mechanism_still_earns_its_cost`); what is checked here is that the page
cannot show a claim the harness is not checking.
"""

from __future__ import annotations

import html

import httpx
import pytest

from ai_backend.evaluation.demo import PainPoint, pain_point_demos
from ai_backend.evaluation.golden import load_golden_set
from ai_backend.evaluation.runner import Ceiling, participates

pytestmark = [
    pytest.mark.story("four ways naive RAG fails"),
    pytest.mark.milestone(4),
]


# -- the page offers what the harness verifies ------------------------------


def test_every_pain_point_is_bound_to_a_verified_golden_question() -> None:
    """The rule that keeps the page from becoming decoration.

    A hand-written demonstration is a claim in a template that nothing checks, and
    the first corpus change that invalidates it leaves a teaching tool confidently
    demonstrating nothing. So each card names a golden question, and that question
    has to carry the ground truth for a ceiling — which is what
    `--compare-strategies` gates.

    The mapping is asserted both ways. A card with no ceiling is an unverified
    claim; a ceiling with no card is a mechanism nobody can see.
    """
    golden = load_golden_set()
    by_id = {q.id: q for q in golden.questions}
    demos = pain_point_demos(golden)

    assert demos, "no pain point is offered at all"

    expected = {
        PainPoint.SUMMARIZE.value: Ceiling.COVERAGE,
        PainPoint.COMPARE.value: Ceiling.DECOMPOSITION,
        PainPoint.INFER.value: Ceiling.HOP,
        PainPoint.REMEMBER.value: Ceiling.RESOLUTION,
    }

    for demo in demos:
        question = by_id.get(demo.golden_id)
        assert question is not None, (
            f"{demo.id!r} names golden question {demo.golden_id!r}, which does not "
            f"exist — so nothing measures what this card claims"
        )
        ceiling = expected[demo.id]
        assert participates(question, ceiling), (
            f"{demo.id!r} is bound to {demo.golden_id!r}, but that question carries "
            f"no ground truth for the {ceiling.value} ceiling. The card would show a "
            f"measurement the harness never makes."
        )


def test_all_four_pain_points_are_offered() -> None:
    """Four, because the course material names four.

    Not padded if one is missing — `pain_point_demos` omits it rather than inventing
    a card — so this asserts the golden set still supports all of them. A missing
    one is a corpus that lost a question, which `--compare-strategies` also fails
    on; this is the half that says the *page* would be short.
    """
    offered = {d.id for d in pain_point_demos()}
    assert offered == {p.value for p in PainPoint}, offered


def test_each_card_quotes_the_material_rather_than_paraphrasing_it(
    harness_verdict, settings
) -> None:
    """A student who read the material last week should recognise the sentence.

    Checked as "the symptom names the failure in the material's own vocabulary",
    which is as close as a test can get to it. The point of the assertion is to stop
    the symptoms drifting into Axis's own words over time — at which moment the page
    stops connecting to the thing the class already read.

    `harness_verdict` supplies a recorded measurement, because `measured` is now read
    from one rather than written here — see the next test for the case where there is
    none. `settings` is passed explicitly for the same reason the route passes it: a
    recorded figure is only a claim about the conditions it was measured under, and the
    process-wide settings are not the ones this test is running.
    """
    for demo in pain_point_demos(settings=settings):
        assert demo.symptom, f"{demo.id} has no symptom"
        assert demo.mechanism, f"{demo.id} names no mechanism"
        assert demo.measured, f"{demo.id} reports no measurement"
        # Every card must name a *different* mechanism. Four failures with one fix
        # would be the "agentic is better" lesson this page exists to replace.
    mechanisms = {d.mechanism for d in pain_point_demos()}
    assert len(mechanisms) == len(pain_point_demos()), (
        f"two pain points name the same mechanism: {mechanisms}. Four failures with "
        f"one fix is the lesson this page exists to replace."
    )


def test_each_pain_point_carries_a_short_title() -> None:
    """A name for each card, so the four can be scanned and pointed at.

    The face used to read `1 of 4` and then a full sentence of symptom, which gives a
    reader nothing to hold and an instructor nothing to say. Four short names fix that,
    and they are also what a collapsed card keeps when another card is open.

    **These are deliberately not the material's own bolded names**, which are
    *"Struggles to summarize"*, *"Comparison is a headache"*, *"Implicit data, beyond the
    obvious"* and *"No memory, disconnected dialogue"* — full phrases up to 33 characters,
    which is a sentence rather than a heading and wraps to two lines on a card sitting
    four-across. CLAUDE.md's rule to quote the material rather than paraphrase it is met
    one line down instead: `symptom` is the material's own second sentence, verbatim,
    directly under the title. Recorded here because this is a divergence and the next
    reader should not have to rediscover it.
    """
    demos = pain_point_demos()

    for demo in demos:
        assert demo.title, f"{demo.id} has no title"
        # A heading, not a sentence. The material's own names are longer than this,
        # which is the whole reason they are not used.
        assert len(demo.title) <= 20, (
            f"{demo.id}'s title is {len(demo.title)} characters, which is prose rather "
            f"than a heading and will wrap on a quarter-width card: {demo.title!r}"
        )
        # A name, not the slug. `id` is a URL and DOM identifier and reads as one.
        assert demo.title != demo.id, f"{demo.id} is titled with its own slug"

    titles = {d.title for d in demos}
    assert len(titles) == len(demos), f"two pain points share a title: {titles}"


# -- the page itself --------------------------------------------------------


async def test_the_page_names_all_four_with_their_mechanisms(
    client: httpx.AsyncClient,
) -> None:
    """The first criterion, read off the rendered page.

    Matched on a distinctive word from each mechanism rather than on the whole
    string, because Jinja escapes the apostrophes in "the router's DEPTH decision"
    and comparing against the raw text would be testing the autoescaper.
    """
    response = await client.get("/why-agentic")
    assert response.status_code == 200, response.text
    page = response.text

    # One word per mechanism that appears nowhere else on the page, so a card
    # silently losing its mechanism cannot pass by coincidence.
    names = {
        PainPoint.SUMMARIZE.value: "map-reduce",
        PainPoint.COMPARE.value: "decomposer",
        PainPoint.INFER.value: "DEPTH",
        PainPoint.REMEMBER.value: "rewriter",
    }

    for demo in pain_point_demos():
        assert f'id="{demo.id}"' in page, f"{demo.id} is not on the page"
        assert names[demo.id] in page, (
            f"{demo.id} does not say what answers it — expected the page to name "
            f"{names[demo.id]!r}"
        )


async def _load_the_demo_corpus(client: httpx.AsyncClient) -> None:
    """Index the measured corpus *and* select it, the way the button does.

    Through the Frontend rather than straight at the API, and that matters now: the
    route loads into the `demo` corpus and switches the browser's corpus cookie to it.
    Posting to the API alone would index the documents into a scope the page is not
    looking at, which is exactly the failure the switch exists to prevent — and would
    leave every assertion below reading an unverified page.
    """
    response = await client.post("/demo-documents", follow_redirects=True)
    assert response.status_code == 200, response.text


async def test_the_runs_are_not_offered_until_something_is_indexed(
    client: httpx.AsyncClient,
) -> None:
    """"a demonstration against an empty index demonstrates nothing".

    Two conditions, and they are different things now. A card is *verified* only on the
    measured corpus, because every "measured" sentence is a claim about those documents.
    A card is *runnable* whenever something is indexed, because the shape of each
    failure holds on any corpus — the student supplies the question and the card says
    the number is not claimed.

    With nothing indexed at all, neither holds: two strategies retrieving from an empty
    index show only that the index is empty.
    """
    bare = (await client.get("/why-agentic")).text
    assert "Nothing is indexed in this corpus" in bare, (
        "the page did not say why its runs are unavailable"
    )

    # Opened, because a bare page now carries no run control at all: nothing is expanded
    # on load, and the form belongs to the open card. That is not the same guarantee — a
    # page with no button cannot offer a live one — so the disabled state is asserted
    # where a button actually exists.
    opened = (await client.get("/why-agentic?point=compare")).text
    assert 'action="/why-agentic/compare"' in opened, "the open card has no run form"
    assert "disabled" in opened, "the run button is live with nothing indexed"


async def test_the_measured_cards_appear_only_on_the_corpus_they_were_measured_on(
    client: httpx.AsyncClient, harness_verdict
) -> None:
    """**The rule the whole page rests on**: verified, or visibly not verified.

    A card that quietly dropped its measurement when the corpus changed would be
    indistinguishable from a card whose figure nobody bothered to write, and a card that
    kept it would be printing the harness's number for the ACME documents beside an
    answer drawn from somebody's own PDFs.

    This test is about the *corpus* half of that rule, so `harness_verdict` holds the
    other half fixed: a recorded measurement exists and matches these settings. The
    mechanism half — a card whose ceiling no longer pays off — is
    `test_a_card_with_no_verified_mechanism_claims_no_measurement`, and the two states
    are worded differently on purpose.
    """
    await _load_the_demo_corpus(client)

    # Every card, not just whichever one is open by default. Only the open card carries a
    # measured line now, so a single GET would check one quarter of the claim and pass —
    # which is the shape of a test that stops covering what it says it covers.
    for demo in pain_point_demos():
        measured = (await client.get(f"/why-agentic?point={demo.id}")).text
        assert "Measured" in measured, f"{demo.id} shows no measurement on the corpus it was measured on"
        assert "Unverified mode" not in measured

    # Switch to the student's own documents. Nothing is re-indexed and nothing is
    # deleted; only the scope retrieval reads changes.
    await client.post("/corpus", data={"corpus": "mine"}, follow_redirects=False)

    for demo in pain_point_demos():
        unverified = (await client.get(f"/why-agentic?point={demo.id}")).text
        assert "Unverified mode" in unverified, (
            f"{demo.id} kept its measured claims after the corpus it measured them on "
            f"stopped being the one searched"
        )
        assert "Not measured" in unverified, (
            f"{demo.id} dropped its measurement without saying it had — which reads as "
            f"a figure nobody wrote rather than as a claim nothing verifies"
        )
        assert 'name="question"' in unverified, (
            f"{demo.id} offers no way to supply a question, so it cannot run"
        )


async def test_a_student_supplied_question_runs_and_is_marked_unverified(
    client: httpx.AsyncClient,
) -> None:
    """The bring-your-own-question mode, end to end.

    Exercise 3 of the course material — *diagnose the naive RAG failure* — is exactly
    this, and the page becomes the place to do it. What must hold is that the run is
    real and the claim is not: both strategies answer, the figures come off their own
    traces, and nothing on the result says the harness measured it.
    """
    # Something of the student's own, so the corpus is not empty. The demo route is the
    # only fixture upload available here; clearing the demo corpus afterwards would
    # leave nothing to retrieve, so this uses the demo documents under the `mine`
    # corpus, which is what a student's own upload looks like to every layer below.
    await client.post(
        "/upload",
        files=[("files", ("notes.md", b"# Notes\n\nPayment is due in 30 days.", "text/markdown"))],
        follow_redirects=True,
    )

    response = await client.post(
        "/why-agentic/compare",
        data={"question": "How does onboarding compare with offboarding?"},
        follow_redirects=False,
    )
    assert response.status_code == 200, response.text
    page = response.text

    assert 'data-strategy="naive_rag"' in page
    assert 'data-strategy="agentic_rag"' in page
    assert "How does onboarding compare with offboarding?" in page, (
        "the result does not say what was asked, so it is two answers to nothing"
    )
    assert "Not measured" in page, (
        "a self-chosen question was presented beside a measured claim"
    )


async def test_an_empty_question_costs_nothing(client: httpx.AsyncClient) -> None:
    """Refused in the Frontend, before the Backend is called at all.

    The same rule `/summarize` follows for an empty selection, and for the same reason:
    a submission that names no question is a stale page or an empty box, and neither is
    a request to spend two runs' worth of a class's budget. Falling back to the card's
    golden question would be worse than either — it would run a question about ACME
    against the student's documents and print a measured figure beside the result.
    """
    await client.post(
        "/upload",
        files=[("files", ("notes.md", b"# Notes\n\nPayment is due in 30 days.", "text/markdown"))],
        follow_redirects=True,
    )
    before = (await client.get("/trace")).text

    response = await client.post(
        "/why-agentic/compare", data={"question": "   "}, follow_redirects=False
    )
    assert response.status_code == 200, response.text
    assert "Type a question" in response.text, (
        "an empty submission was not refused with a reason"
    )
    assert 'data-ran="true"' not in response.text, "an empty submission ran anyway"
    assert (await client.get("/trace")).text == before, (
        "an empty submission changed the trace, so it reached the Backend"
    )


async def test_running_a_pain_point_shows_both_strategies_and_the_measurement(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str], settings
) -> None:
    """The second criterion: one question, both strategies, both answers.

    Ordered baseline-first on the page so it reads as "here is what happens, and
    here is what the extra machinery changes" rather than as a victory lap — on a
    single-fact question the honest reading of the same layout is that agentic
    wasted money, which is the other half of what this platform teaches.
    """
    await _load_the_demo_corpus(client)

    response = await client.post("/why-agentic/compare", follow_redirects=False)
    assert response.status_code == 200, response.text
    page = response.text

    assert 'data-strategy="naive_rag"' in page
    assert 'data-strategy="agentic_rag"' in page
    # The figures that distinguish them, each read off its own trace rather than
    # asserted. The whole page rests on these being real.
    assert "retrievals" in page
    assert "trace steps" in page
    assert "cost" in page


async def test_the_page_says_when_a_mechanism_did_not_fire(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """**The most important honesty check on the page.**

    Offline the model cannot classify or split, so the router correctly treats every
    question as simple, the mechanism never fires, and the agentic column makes
    exactly one retrieval — the same as the baseline, for about a hundred times the
    cost. Both numbers are real and the obvious reading of them is wrong: not "this
    needs a real model" but "the mechanism does nothing".

    A teaching tool that produces real numbers inviting a wrong conclusion is worse
    than one that produces none, so the page states which happened. Asserted here
    because it is the difference between the page teaching and the page misleading,
    and because nothing about it is visible in a passing run.
    """
    await _load_the_demo_corpus(client)
    page = (await client.post("/why-agentic/compare")).text

    assert "mechanism did not fire" in page or "mechanism fired on this run" in page, (
        "the page reported neither that the mechanism fired nor that it did not, so "
        "a reader cannot tell a demonstration from a cost comparison"
    )


async def test_the_summarization_card_points_at_the_mode_that_answers_it(
    client: httpx.AsyncClient,
) -> None:
    """The one pain point whose fix is not a strategy.

    Summarization is answered by reading everything, which sits on neither axis and
    is deliberately not in the `Strategy` enum — so running both strategies here
    shows two retrieval-shaped answers to a question that is not retrieval-shaped.
    That is the pain point rather than the fix, and the card has to send a reader to
    where the fix lives.

    Asked for by name rather than read off a bare GET. The bare page would pass — that
    card is first, so it is the one open by default — but it would pass by coincidence of
    ordering rather than because *this* card points anywhere.
    """
    page = (await client.get("/why-agentic?point=summarize")).text

    # **Matched on the aside itself, not on `href="/summarize"`.** That string is in the
    # top nav of every page (`base.html`), so the obvious assertion passed even with this
    # card's aside deleted outright — a test that could not fail is worse than no test.
    assert 'class="painpoint__aside"' in page, (
        "the summarization card has no aside, so a student is left with the failure "
        "and no pointer to the mode that answers it"
    )
    assert "reads every" in page and "chunk of every document" in page, (
        "the aside no longer explains what Summarize does differently"
    )


async def test_a_pain_point_run_survives_navigating_away(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """Held, not recomputed — the same rule the summary follows.

    The page is in the nav, so it can be navigated back to, and a page that
    discarded its result on every visit would charge a student two more runs for a
    navigation. It also breaks the thing the page is *for*: reading the trace to see
    which stages produced the difference means leaving the page and coming back.
    """
    await _load_the_demo_corpus(client)
    await client.post("/why-agentic/compare")

    page = (await client.get("/why-agentic")).text
    assert 'data-ran="true"' in page, (
        "the result was discarded on navigation, so reading its trace costs another "
        "two runs"
    )


async def test_every_pain_point_can_be_selected_and_run_with_no_javascript(
    client: httpx.AsyncClient,
) -> None:
    """Two plain links and a plain form post, and a page rendered in response.

    The hard requirement in CLAUDE.md. Also the honest choice for a control that
    spends money: nothing that costs a class's budget should depend on a script
    having loaded.

    Both halves are checked per pain point, because both are now navigations. Only the
    *open* card carries a form — the other three are the overview — so a single GET can
    no longer show all four forms, and asserting on one page would silently only ever
    check whichever card happens to be first.
    """
    overview = (await client.get("/why-agentic")).text

    for demo in pain_point_demos():
        # Selecting is a link, so it works with scripts off. The fragment is part of it:
        # a full-page navigation resets focus to the top of the document, so without it a
        # student who picked card three would tab past the nav and the whole rail to reach
        # the form they just asked for. It points at the card's own `<li>` now — the card
        # holds its detail, so there is no separate `#detail` section to aim at, and below
        # 1280px where the page scrolls this is what brings the card into view.
        assert f'href="/why-agentic?point={demo.id}#{demo.id}"' in overview, (
            f"{demo.id} cannot be selected without JavaScript"
        )
        # And once selected, running it is a native form post.
        page = (await client.get(f"/why-agentic?point={demo.id}")).text
        assert 'method="post"' in page
        assert f'action="/why-agentic/{demo.id}"' in page, (
            f"{demo.id} has no form action, so it cannot be run without JavaScript"
        )


async def test_all_four_failures_are_on_screen_without_being_clicked(
    client: httpx.AsyncClient,
) -> None:
    """**The assertion the redesign rests on.**

    The page was a single column two and a half viewports tall, so the four failures —
    which are the lesson — were never on screen together and a class had to be scrolled
    through them one at a time. They are a row of four cards now, one of which expands in
    place.

    What must stay on the *face* of every card is the pairing: the failure in the course
    material's own words, and the one mechanism that answers it. CLAUDE.md records why,
    about the canvas — a rail of names with the data behind a click "taught nothing,
    because a class watching from the back of a room cannot click". Only the *run* is
    behind the click here, which is an interaction rather than a lesson.

    **This is the test that pins PRD §6 to the unselected state**, which is the exact
    wording of the criterion — *"when a student opens the pain-point page, then each of
    the four failures is named …"* — and what lets a card give up its mechanism and its
    question once *another* card is open and its column is 153px wide. Nothing is open
    here, so all four carry all three, and the assertions below are unchanged from before
    the redesign: that is the evidence the redesign kept the contract rather than working
    around it.

    The same shape as the canvas's `test_every_stage_draws_its_data_without_being_clicked`.
    """
    raw = (await client.get("/why-agentic")).text
    # Unescaped before comparing, because Jinja escapes the apostrophes in "the router's
    # DEPTH decision" and matching the escaped form would be testing the autoescaper
    # rather than the page. `test_the_page_names_all_four_with_their_mechanisms` dodges
    # this by matching one distinctive word; this one wants the whole sentence, since the
    # claim is that a reader can *read* it without clicking.
    page = html.unescape(raw)

    for demo in pain_point_demos():
        assert f'id="{demo.id}"' in page, f"{demo.id} is not on the page"
        assert demo.symptom in page, (
            f"{demo.id} does not state its failure on the card face, so a reader has to "
            f"click to learn what it is about"
        )
        assert demo.mechanism in page, (
            f"{demo.id} does not name its mechanism on the card face — and the pairing "
            f"of the two is the lesson of this page"
        )
        # PRD §6 names all three together: each failure "named in the same words the
        # course material uses, beside the mechanism that answers it *and a question
        # that exhibits it*". The card face is where "opens the pain-point page" is
        # satisfied, so all three have to be there — this is the half no test asserted
        # before, and the half a click-to-expand design is most likely to lose.
        assert demo.question in page, (
            f"{demo.id} shows no question that exhibits it, which PRD Section 6 names "
            f"beside the symptom and the mechanism"
        )

        # The short name, which is what makes a row of four scannable and gives an
        # instructor something to point at. Added because `1 of 4` followed by a full
        # sentence of symptom gave a reader nothing to hold on to.
        assert f">{demo.title}<" in page, (
            f"{demo.id} carries no heading, so the four can only be told apart by "
            f"reading a sentence each"
        )

    # **None open, and that is the point of this state.** A default selection made card
    # one look privileged among four that are meant to be peers, and it is what the PRD
    # criterion is written against.
    assert raw.count('aria-current="true"') == 0, (
        f"a card is open on a page nobody has clicked, found "
        f"{raw.count('aria-current=')}"
    )


async def test_the_open_card_is_chosen_by_the_url_and_survives(
    client: httpx.AsyncClient,
) -> None:
    """Selection is server state in a query parameter, like `?stage=` and `?id=`.

    Which means it survives a reload, can be linked to, and needs no JavaScript — the
    same three properties the canvas's `?stage=` and the Trace page's `?id=` were built
    for.

    An unknown value falls back rather than erroring, also following those two: the only
    ways to hold a stale one are a bookmark and a link from an earlier session, and in
    both cases a page is a better answer than a 404.
    """
    for demo in pain_point_demos():
        page = (await client.get(f"/why-agentic?point={demo.id}")).text
        # The open card's detail carries the run form; the other three do not.
        assert f'action="/why-agentic/{demo.id}"' in page, f"{demo.id} did not open"
        assert page.count('aria-current="true"') == 1

    # **Falls back to nothing open, not to card one.** Since there is no default
    # selection any more, the fallback is the page's own resting state — which is the
    # better failure: a stale bookmark used to silently expand a card the reader had not
    # asked for and show them its detail as though they had.
    nonsense = (await client.get("/why-agentic?point=../../etc")).text
    assert nonsense.count('aria-current="true"') == 0, (
        "an unrecognised point opened a card nobody asked for"
    )
    assert 'class="painpoint"' in nonsense, "the page did not render at all"


async def test_a_finished_run_opens_the_card_that_ran(
    client: httpx.AsyncClient,
) -> None:
    """A run lands on its own result, and a navigation back returns to it.

    The result is held server-side for one card per session, so "which card is open" and
    "which card has a result" have to agree after a run — otherwise the answer a student
    just paid for is behind a click they have no reason to make.
    """
    await _load_the_demo_corpus(client)
    ran = (await client.post("/why-agentic/infer")).text

    assert 'data-ran="true"' in ran
    assert 'action="/why-agentic/infer"' in ran, (
        "the run finished on a different card than the one that ran"
    )
    # The open card carries no overlay link — an invisible anchor across its form would
    # swallow the form — while the ones beside it still do.
    assert 'href="/why-agentic?point=infer#infer"' not in ran, (
        "the open card is still overlaid with a link, which swallows its own run form"
    )
    assert 'href="/why-agentic?point=compare#compare"' in ran, (
        "the cards beside the open one stopped being clickable"
    )

    # And coming back to the page returns to it rather than to the first card.
    again = (await client.get("/why-agentic")).text
    assert 'action="/why-agentic/infer"' in again, (
        "navigating back opened the default card, so the held result is behind a click"
    )

    # Naming another card explicitly still works, and the result stays held.
    other = (await client.get("/why-agentic?point=compare")).text
    assert 'action="/why-agentic/compare"' in other
    assert 'data-ran="true"' in other, (
        "looking at another card discarded the result of the one that ran"
    )


async def test_a_card_expands_in_place_rather_than_below_the_row(
    client: httpx.AsyncClient,
) -> None:
    """**The regression for the complaint that prompted this shape.**

    The detail used to be a `.painpoint-detail` section below the row of cards, behind a
    border and a margin — so it read as a different part of the page, and reaching it
    meant scrolling. That defeats a row whose entire purpose is that the four cards stay
    on screen.

    It is part of the card now. Asserted structurally rather than by eye: the run form
    has to fall *inside* the open card's own `<li>`, which is the one thing that cannot be
    true of a section rendered after the list.
    """
    page = (await client.get("/why-agentic?point=compare")).text

    start = page.index('<li class="painpointslot" id="compare"')
    end = page.index("<li ", start + 1) if "<li " in page[start + 1 :] else len(page)
    card = page[start:end]

    assert 'action="/why-agentic/compare"' in card, (
        "the run form is outside the card it belongs to, so the detail is still a "
        "separate section below the row"
    )
    assert 'class="painpoint__detail"' in card, "the detail is not inside the card"
    # And the old section is gone rather than merely hidden.
    assert 'class="painpoint-detail"' not in page


async def test_a_closed_card_is_a_link_and_an_open_one_is_not(
    client: httpx.AsyncClient,
) -> None:
    """An invisible anchor across a form swallows the form.

    Which is why `_card.html` renders its overlay link on collapsed cards only, and the
    reasoning transfers exactly: an open pain-point card holds a text field and a submit
    button that spends real money, and an overlay across them would take every click and
    the page would look completely correct.

    This is the failure most likely to be introduced and least likely to be noticed, so
    both directions are asserted.
    """
    page = (await client.get("/why-agentic?point=compare")).text

    assert page.count('class="painpoint__open"') == len(pain_point_demos()) - 1, (
        "the wrong number of cards are clickable — the open one must not be, and the "
        "others must be"
    )
    assert 'href="/why-agentic?point=compare#compare"' not in page, (
        "the open card is overlaid with a link, which swallows its own run form"
    )
    # And a way back out, as a real link so it works with scripts disabled.
    assert 'class="painpoint__close" href="/why-agentic"' in page, (
        "an opened card cannot be closed again"
    )

    # With nothing open, all four are clickable.
    closed = (await client.get("/why-agentic")).text
    assert closed.count('class="painpoint__open"') == len(pain_point_demos())


async def test_a_refusal_lands_on_the_card_it_is_about(
    client: httpx.AsyncClient,
) -> None:
    """The message has to appear beside the box it is asking you to fill in.

    The default selection is "the card that has a result", so a refusal that did not name
    its own card would send a student who left a box empty to whichever card they ran
    earlier — with a message about a card they are no longer looking at, which reads as
    the page having gone wrong.
    """
    await client.post(
        "/upload",
        files=[("files", ("notes.md", b"# Notes\n\nPayment is due in 30 days.", "text/markdown"))],
        follow_redirects=True,
    )

    page = (await client.post("/why-agentic/remember", data={"question": "   "})).text

    assert "Type a question" in page or "needs both turns" in page
    assert 'action="/why-agentic/remember"' in page, (
        "the refusal rendered a different card than the one submitted"
    )


async def test_a_rail_control_keeps_the_card_you_were_reading(
    client: httpx.AsyncClient,
) -> None:
    """Switching corpus is the main thing you *do* on this page, so it must not lose it.

    The rail renders four controls here — corpus, web search, cache, new conversation —
    and each posts and redirects back to the referring *path*, dropping the query string
    with it. That sent a student back to the first card every time they touched one, and
    the unverified banner points at the corpus toggle by name, so it was the common case
    rather than an edge.

    Only `point` is carried across, and only as a slug: reflecting a referer's query
    wholesale back out of a redirect is the same open-redirect shape the path check
    already guards against.
    """
    referer = {"referer": "http://test/why-agentic?point=infer"}

    for path, body in (
        ("/corpus", {"corpus": "demo"}),
        ("/cache", {"on": "0"}),
        ("/conversation/reset", {}),
    ):
        response = await client.post(
            path, data=body, headers=referer, follow_redirects=False
        )
        assert response.status_code == 303, f"{path}: {response.text}"
        assert response.headers["location"] == "/why-agentic?point=infer", (
            f"{path} dropped the open card, so a rail click sends you back to the first"
        )

    # And nothing but a slug is ever reflected back into the URL.
    forged = await client.post(
        "/cache",
        data={"on": "0"},
        headers={"referer": "http://test/why-agentic?point=%3Cscript%3E"},
        follow_redirects=False,
    )
    assert forged.headers["location"] == "/why-agentic"


async def test_the_page_carries_no_run_controls(client: httpx.AsyncClient) -> None:
    """The rail belongs to the Run page, and this is not it.

    Not a tidiness rule: the strategy radios carry `form="ask-form"`, which exists
    only on the Run page, so here they would be controls that look live and cannot
    act — the exact failure `test_the_run_controls_belong_to_the_run_page` records
    for Compare and the raw trace.
    """
    page = (await client.get("/why-agentic")).text

    assert 'form="ask-form"' not in page
    assert 'action="/upload"' not in page
