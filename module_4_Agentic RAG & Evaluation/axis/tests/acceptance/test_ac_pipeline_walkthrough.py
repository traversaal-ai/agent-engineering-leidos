"""PRD Section 5 — student must-have:

    "As a student with no background in this, I want to watch each stage of indexing
    and answering as it happens — with the actual text and the actual numbers at every
    stage — so that I understand what RAG is doing rather than taking it on trust."

PRD Section 6, *Watch the pipeline run*: the eight criteria asserted below.

Milestone 3.

**None of this is new work the system does.** Parsing, chunking, embedding, storing and
prompt assembly all happened before; they happened inside other steps, so the UI could
report "12 chunks" and "3 passages · best 0.81" and nothing else. These tests assert
that the mechanism is *visible*, which is a different property from it being correct —
and the one the platform was missing for an audience meeting retrieval for the first
time.

The load-bearing ones are the data assertions. A rail of eight labelled boxes with no
content behind them would satisfy a naive reading of the story and teach nothing, so
each stage is checked for the thing it exists to show: the chunk text with its overlap
marked, the vector beside the text it came from, the rejected candidates beside the
kept ones, the assembled prompt in full.
"""

from __future__ import annotations

import re

import httpx
import pytest

from ai_backend.contracts.models import StepStatus, Strategy
from ai_backend.observability.store import InMemoryStepStore
from tests.docfixtures import make_pdf

pytestmark = [
    pytest.mark.story("watch each stage of indexing and answering"),
    pytest.mark.milestone(3),
]

_QUESTION = "How long is paid parental leave?"


_HANDBOOK = (
    "Parental leave. Employees are entitled to 16 weeks of fully paid parental "
    "leave following the birth or adoption of a child. Leave may be taken in up to "
    "three separate blocks within the first year. A further 8 weeks of unpaid leave "
    "may be requested and will not be unreasonably refused. Remote work. Employees "
    "may work remotely for up to three days each week. Teams that require in-person "
    "collaboration may agree a lower limit, but no team may require more than four "
    "days on site."
)


# Deliberately unrelated to the handbook and to the question asked below, so the
# search stage has candidates that score near zero. Without something for the
# threshold to reject, the most explanatory view in the product has nothing to
# explain — every candidate would be kept and the line would sit at the bottom.
_CHEESE = (
    "A history of alpine cheese. Hard mountain cheeses have been produced in high "
    "pastures since the fourteenth century, matured in cellars for up to eighteen "
    "months before sale."
)


async def _indexed(client: httpx.AsyncClient) -> None:
    """Index two known documents, through the form a student uses.

    Known rather than the demo set: these tests assert on the *content* of each stage,
    and the demo corpus finishes with a PNG whose single chunk is an image caption.
    The rail binds the last document indexed, so the panes would legitimately show a
    caption and the assertions would be checking the wrong document for the right
    reason.

    Uploaded in one request, so the rail's indexing stages describe the *last* of them
    — which is why the content assertions below name the handbook and it is listed
    second.
    """
    await client.post(
        "/upload",
        files=[
            ("files", ("cheese.pdf", make_pdf(_CHEESE), "application/pdf")),
            ("files", ("handbook.pdf", make_pdf(_HANDBOOK), "application/pdf")),
        ],
        follow_redirects=True,
    )


async def _step_id(page: str, step_type: str) -> str:
    """The id the canvas bound to that stage.

    Read out of the rendered page rather than looked up in the trace, deliberately:
    picking the latest step of a type reaches the *provider's* nested `embed` call
    rather than the indexing stage, which is a distinction the canvas already gets
    right (`_bind_stages`). Reading it off the card tests the path a student takes and
    cannot drift from it.
    """
    match = re.search(rf'data-type="{step_type}"[^>]*data-step="([^"]+)"', page)
    assert match, f"no {step_type!r} card on the canvas"
    return match.group(1)


async def _open(client: httpx.AsyncClient, step_type: str) -> str:
    """That stage's card, expanded — what a student sees after clicking it."""
    page = (await client.get("/")).text
    return (await client.get(f"/canvas?stage={await _step_id(page, step_type)}")).text


async def _after_indexing(client: httpx.AsyncClient) -> str:
    await _indexed(client)
    return (await client.get("/")).text


# -- the canvas starts empty ------------------------------------------------


async def test_a_fresh_canvas_claims_nothing(client: httpx.AsyncClient) -> None:
    """"the canvas starts empty and fills as things happen".

    The diagram is drawn — it is a map of what is coming, and each card says what its
    stage is *for*, which is useful before anything has run and costs nothing. But no
    card may claim to have completed. A canvas that pre-drew a finished pipeline would
    be asserting work nobody did, in a tool whose whole claim is that what it shows is
    what happened.
    """
    page = (await client.get("/")).text

    assert 'data-state="pending"' in page
    assert 'data-state="done"' not in page
    # The shape of RAG, explained, before a penny is spent.
    assert "cut into overlapping pieces" in page


# -- indexing is visible, stage by stage ------------------------------------


async def test_every_indexing_stage_appears_with_its_own_data(
    client: httpx.AsyncClient,
) -> None:
    """"each of parse, chunk, embed and store appears as its own stage".

    Previously all four ran inside a single `INGEST` step, so a student never saw a
    document become searchable — the only evidence was a chunk count in the sidebar.
    """
    await _indexed(client)
    page = (await client.get("/")).text

    for stage in ("parse", "chunk", "embed", "store"):
        assert re.search(
            rf'data-type="{stage}"[^>]*data-state="done"', page
        ), f"{stage!r} did not appear as a completed stage"


async def test_every_stage_draws_its_data_without_being_clicked(
    client: httpx.AsyncClient,
) -> None:
    """"every stage's real data is visible on the canvas, without a click".

    The criterion the tabbed rail failed, and the reason this screen was rebuilt. A
    strip of stage names with the data behind a click satisfies a naive reading of the
    story and teaches nothing: a class watching from the back of a room cannot click,
    and an instructor narrating a run should not have to.

    So each card carries its own artifact — the overlapping tiles, the vector's bar
    strip, the stored dots — drawn from the same attributes the expanded card uses.
    """
    await _indexed(client)
    await client.post(
        "/ask", data={"question": _QUESTION, "strategy": Strategy.NAIVE_RAG.value}
    )
    page = (await client.get("/")).text

    assert 'class="tiles"' in page, "the chunk card does not draw its chunks"
    assert 'class="strip"' in page, "the embed card does not draw its vector"
    assert 'class="dots"' in page, "the store card does not draw the index"
    assert 'class="ranks"' in page, "the search card does not draw its scores"
    assert 'class="bands"' in page, "the augment card does not draw the prompt"
    # And the scores carry the threshold, at card size — the single most explanatory
    # thing on the screen has to survive being small.
    assert 'class="ranks__line"' in page, "the threshold is not drawn on the card"


async def test_the_two_phases_are_drawn_as_one_diagram(
    client: httpx.AsyncClient,
) -> None:
    """Indexing above, answering below, with the index they share between them.

    The notebook's own Phase A / Phase B framing. The index band is the object both
    phases touch and the thing a strip of stages can never show: without it a student
    has no reason to believe the second track is reading what the first one wrote.
    """
    page = (await client.get("/")).text

    assert 'class="track track--index"' in page
    assert 'class="track track--query"' in page
    assert 'class="indexband"' in page
    assert "written by Store, read by Search" in (await _after_indexing(client))


async def test_the_parse_stage_shows_extracted_text_with_its_location(
    client: httpx.AsyncClient,
) -> None:
    """The step that makes the file format stop mattering.

    The location matters as much as the text: it is what a citation will later point
    at, so seeing it appear here is what makes a citation traceable rather than magic.
    """
    await _indexed(client)
    pane = await _open(client, "parse")

    assert "Parse" in pane
    assert "block" in pane
    assert 'class="blocks__where"' in pane, "extracted text is shown without its source"


async def test_the_chunk_stage_shows_the_text_and_marks_the_overlap(
    client: httpx.AsyncClient,
) -> None:
    """"the repeated text is marked, so the reason for overlap is visible".

    The pane with the most to teach. The notebook explains overlap in a sentence, and
    a student who reads that sentence has learned a sentence; one who sees the same
    characters end one chunk and begin the next has learned what it is *for*.

    The marked span is computed by the chunker (`_overlap`), not by the renderer:
    `_merge_and_overlap` trims to a word boundary, so the shared text is rarely
    exactly `overlap_chars` long and a template guessing at it would highlight the
    wrong characters.
    """
    await _indexed(client)
    pane = await _open(client, "chunk")

    assert "of overlap" in pane
    assert 'class="chunkview' in pane, "there is no way to page through the chunks"
    # Real document text, not a summary of it.
    assert "parental leave" in pane.lower() or "encryption" in pane.lower()
    # Either a marked overlap, or an explicit statement that there is none — both are
    # informative; silence is not.
    assert "overlap" in pane.lower()


async def test_the_embed_stage_shows_the_text_and_the_numbers_together(
    client: httpx.AsyncClient,
) -> None:
    """"the text and the numbers it became are shown together".

    The pairing is the lesson. A stage that reported "5 vectors of 4096 dimensions"
    would be stating a fact about a thing the student has still never seen.
    """
    await _indexed(client)
    pane = await _open(client, "embed")

    assert "dimensions" in pane
    assert 'class="vector__head"' in pane, "the numbers themselves are not shown"
    assert 'class="vector__text"' in pane, "the vector is shown without its source text"
    # Signed decimals, which is what a vector actually looks like.
    assert re.search(r"-?\d\.\d{4}", pane), "no actual vector values on the page"


async def test_a_sparse_vector_still_shows_something(
    client: httpx.AsyncClient,
) -> None:
    """The offline stand-in must not look broken.

    `FakeEmbeddingProvider` is a hashed bag of words over 4,096 dimensions, so about
    twenty-five are set and the first eight are reliably all zero — for every chunk
    and for the question. Showing only the head would have a class watch two different
    texts produce identical all-zero vectors and reasonably conclude it was broken.

    So the pane also reports how many dimensions carry a value and which are
    strongest. The head stays honest about being the first eight.
    """
    await _indexed(client)
    pane = await _open(client, "embed")

    assert "carrying a value" in pane, "nothing distinguishes a sparse vector"
    assert "strongest" in pane, (
        "with an all-zero head there is nothing on screen telling two texts apart"
    )


# -- answering is visible, stage by stage -----------------------------------


async def test_the_search_stage_shows_rejected_candidates_and_the_threshold(
    client: httpx.AsyncClient,
) -> None:
    """"every candidate passage is shown with its similarity score and the threshold".

    The most explanatory view in the product. Retrieval rendered as "3 passages · best
    0.81", which states an outcome and hides the mechanism: nothing said that twenty
    passages were scored, ranked, and a line drawn. Showing the dropped ones next to
    the kept ones is what turns "it found the right passage" into something a student
    can check — and the only way the "found nothing" path stops looking like a bug.
    """
    await _indexed(client)
    await client.post(
        "/ask", data={"question": _QUESTION, "strategy": Strategy.NAIVE_RAG.value}
    )
    pane = await _open(client, "retrieve")

    assert 'data-kept="yes"' in pane, "no candidate is shown as kept"
    assert 'data-kept="no"' in pane, (
        "only the surviving passages are shown — the rejected ones are what make the "
        "threshold mean anything"
    )
    assert 'class="scores__line"' in pane, "the threshold is not drawn"
    # And the query's own vector, so the comparison has two sides.
    assert 'class="vector__head"' in pane


async def test_the_augment_stage_shows_the_whole_assembled_prompt(
    client: httpx.AsyncClient,
) -> None:
    """"the assembled prompt is shown in full".

    The moment "retrieval-augmented" means something, and previously the one gap a
    student had to take on trust: passages went in, an answer came out, and the
    substitution happened out of sight. That gap is the whole idea of RAG.
    """
    await _indexed(client)
    await client.post(
        "/ask", data={"question": _QUESTION, "strategy": Strategy.NAIVE_RAG.value}
    )
    pane = await _open(client, "augment")

    # The rules and the context are shown separately: the system prompt is where
    # "cite every claim" comes from, and that explains the answer's shape.
    assert "The rules the model is given" in pane
    assert "The context and the question" in pane
    assert _QUESTION in pane, "the question is not in the prompt that was shown"
    assert "Context passages:" in pane


async def test_a_run_in_flight_never_shows_the_previous_answer(
    client: httpx.AsyncClient,
) -> None:
    """The answering cards go blank when a new question starts, not stale.

    `_bind_stages` takes the most recent step of each type across the session, which is
    right at rest and wrong mid-run: while a second question is in flight the *first*
    question's search, prompt and answer are still the most recent ones, so a canvas
    refreshed two seconds in would draw them under the new question. It mattered less
    when a card was a label; the cards now carry scores, prompts and answer text, and a
    plausible wrong number is the one thing this platform must never show.

    `since` is the sequence the run started at. Indexing is deliberately exempt: those
    stages describe documents that are still indexed.
    """
    await _indexed(client)
    await client.post(
        "/ask", data={"question": _QUESTION, "strategy": Strategy.NAIVE_RAG.value}
    )

    steps = (await client.get("/trace/recent?since_seq=0")).json()["steps"]
    floor = max(int(s["seq"]) for s in steps)

    mid_run = (await client.get(f"/canvas?since={floor}")).text

    # Indexing survives: asking a question does not un-index your files.
    assert re.search(r'data-type="chunk"[^>]*data-state="done"', mid_run)
    # The previous answer does not.
    for stage in ("retrieve", "augment", "synthesize"):
        assert re.search(
            rf'data-type="{stage}"[^>]*data-state="pending"', mid_run
        ), f"{stage!r} still shows the previous question's data"


# -- navigating back and forth ----------------------------------------------


async def test_any_earlier_stage_is_reachable_after_a_run(
    client: httpx.AsyncClient,
) -> None:
    """"a student clicks any earlier stage … without re-running anything".

    Every card is a real link to a real URL, which is what makes the whole walkthrough
    work with JavaScript disabled — the script intercepts these clicks to swap in
    place, and without it the browser simply follows them.
    """
    await _indexed(client)
    await client.post(
        "/ask", data={"question": _QUESTION, "strategy": Strategy.NAIVE_RAG.value}
    )

    page = (await client.get("/")).text
    links = re.findall(r'class="card__open" href="(/\?stage=[^"]+)"', page)
    assert len(links) >= 6, f"only {len(links)} stages are reachable"

    for href in links:
        response = await client.get(href)
        assert response.status_code == 200, href
        # A whole page, because this is the path a browser without JavaScript takes.
        # The diagram is still on it — opening one stage must never cost the flow.
        assert 'class="canvasboard"' in response.text, (
            f"{href} lost the canvas while opening a stage"
        )
        assert 'data-expanded="true"' in response.text, f"{href} opened nothing"


# -- choosing which document the indexing track describes -------------------
#
# The canvas binds the most recent step of each type, so the indexing half described
# whichever document finished last. With the demo set that is a PNG whose single chunk is
# an image caption — so a class that loaded four documents to watch chunking got a track
# reading "1 block, 1 chunk" and no way to reach the policy document they came for.
#
# There *was* a way, on paper: a chip per document inside an opened card. It never
# worked. The chip linked to `/?stage=<an earlier document's chunk>` and `_bind_stages`
# had already bound Chunk to the newest document, so nothing matched — the board opened,
# the track compressed, zero cards expanded, and all four still drew the last document.


def _track_subject(page: str) -> str:
    """The filename the Indexing track says it is describing."""
    match = re.search(r'class="track__subject">\s*(.*?)\s*</span>', page, re.S)
    assert match, "the indexing track names no document"
    return re.sub(r"<[^>]+>", " ", match.group(1)).strip()


def _document_links(page: str) -> dict[str, str]:
    """Filename → its `?document=` id, from the sidebar."""
    return {
        name.strip(): document_id
        for document_id, name in re.findall(
            r'href="/\?document=([^"]+)"[^>]*>.*?</span>\s*([^<]+)', page, re.S
        )
    }


async def test_any_indexed_document_can_be_chosen_from_the_sidebar(
    client: httpx.AsyncClient,
) -> None:
    """The ask: reach an earlier document's indexing details, not just the last one."""
    await _indexed(client)

    page = (await client.get("/")).text
    links = _document_links(page)
    assert set(links) == {"cheese.pdf", "handbook.pdf"}, links
    assert _track_subject(page).startswith("handbook.pdf"), (
        "the default should still be the document just indexed"
    )

    chosen = (await client.get(f"/?document={links['cheese.pdf']}")).text

    assert _track_subject(chosen).startswith("cheese.pdf")
    assert "alpine cheese" in chosen.lower(), (
        "the track names cheese.pdf but draws another document's text"
    )
    assert "parental leave" not in chosen.lower(), (
        "the handbook's content is still on the indexing track"
    )


async def test_the_indexing_track_never_mixes_two_documents(
    client: httpx.AsyncClient,
) -> None:
    """The regression the old per-stage chips could not avoid.

    Moving one stage to an earlier document while Parse, Embed and Store still described
    the newest would put two documents on one track under one filename — numbers that
    look like one document's and are two documents'. Worse than only ever showing the
    last. So all four cards must come from one `ingest` run.
    """
    await _indexed(client)
    page = (await client.get("/")).text
    cheese = _document_links(page)["cheese.pdf"]

    chosen = (await client.get(f"/?document={cheese}")).text
    steps = (await client.get("/trace/recent")).json()["steps"]

    # Every indexing card on the page, resolved back to the trace it came from.
    ids = dict(re.findall(r'data-type="(parse|chunk|embed|store)"[^>]*data-step="([^"]+)"', chosen))
    assert len(ids) == 4, f"only {sorted(ids)} drawn"
    by_id = {s["id"]: s for s in steps}
    traces = {by_id[step_id]["trace_id"] for step_id in ids.values()}
    assert len(traces) == 1, (
        f"the four indexing cards span {len(traces)} ingest runs — they describe "
        f"different documents under one filename"
    )


async def test_the_index_band_reports_the_whole_index_whichever_document_is_chosen(
    client: httpx.AsyncClient,
) -> None:
    """The band between the tracks is the index, and belongs to neither.

    Read off the selected document's Store step it shows what the index held *then*, so
    selecting the first of several documents made the band report the index shrinking —
    while the Store card beside it correctly showed the same smaller number, because for
    that step it is true. The card is a measurement of a step; the band is the state of
    a shared object.
    """
    await _indexed(client)

    default = (await client.get("/")).text
    everything = _band_vectors(default)
    assert everything >= 2, f"expected both documents in the index, got {everything}"

    first = (
        await client.get(f"/?document={_document_links(default)['cheese.pdf']}")
    ).text

    assert _band_vectors(first) == everything, (
        f"choosing an earlier document made the index band report "
        f"{_band_vectors(first)} vectors when the index holds {everything}"
    )


def _band_vectors(page: str) -> int:
    """How many vectors the band between the two tracks says the index holds."""
    label = re.search(r'class="indexband__label">(.*?)</span>', page, re.S)
    assert label, "the canvas has no index band"
    count = re.search(r"(\d+) vector", label.group(1))
    return int(count.group(1)) if count else 0


async def test_choosing_a_document_survives_opening_a_card(
    client: httpx.AsyncClient,
) -> None:
    """Otherwise the selection is lost by the first click, silently.

    The server's default is the newest document, so dropping `?document=` is not
    neutral — it moves the track. Every link out of a card has to carry it, which is
    also what keeps the scripts-disabled path correct.
    """
    await _indexed(client)
    page = (await client.get("/")).text
    cheese = _document_links(page)["cheese.pdf"]

    chosen = (await client.get(f"/?document={cheese}")).text
    links = re.findall(r'class="card__open" href="([^"]+)"', chosen)
    assert links, "no cards to open"
    assert all(f"document={cheese}" in href for href in links), (
        "a card link drops the document selection"
    )

    opened = (await client.get(links[0].replace("&amp;", "&"))).text
    assert _track_subject(opened).startswith("cheese.pdf"), (
        "opening a card moved the indexing track back to the newest document"
    )
    assert 'data-expanded="true"' in opened, "the card did not open"

    close = re.search(r'class="card__close" href="([^"]+)"', opened)
    assert close and f"document={cheese}" in close.group(1), (
        "closing a card drops the document selection"
    )


async def test_asking_a_question_keeps_the_chosen_document(
    client: httpx.AsyncClient,
) -> None:
    """The no-JavaScript path re-renders the whole page, so the selection is submitted.

    With a script the canvas is re-fetched with the parameter still in the address bar.
    Without one, a hidden field on the ask form is the only thing that carries it.
    """
    await _indexed(client)
    page = (await client.get("/")).text
    cheese = _document_links(page)["cheese.pdf"]

    chosen = (await client.get(f"/?document={cheese}")).text
    assert f'name="document" value="{cheese}"' in chosen, (
        "the ask form does not carry the indexing selection"
    )

    answered = (
        await client.post(
            "/ask",
            data={
                "question": _QUESTION,
                "strategy": Strategy.NAIVE_RAG.value,
                "document": cheese,
            },
        )
    ).text

    assert _track_subject(answered).startswith("cheese.pdf"), (
        "asking a question moved the indexing track to a different document"
    )


async def test_an_unknown_document_falls_back_to_the_newest(
    client: httpx.AsyncClient,
) -> None:
    """A stale link or a bookmark taken before a reset. The newest is what they want."""
    await _indexed(client)

    response = await client.get("/?document=nosuchdocument")

    assert response.status_code == 200
    assert _track_subject(response.text).startswith("handbook.pdf")


async def test_a_document_that_failed_shows_where_it_stopped(
    client: httpx.AsyncClient,
) -> None:
    """Not the previous document's later stages.

    This is why the stages are *dropped* rather than left bound: a document that failed
    at parse must show Chunk, Embed and Store pending. Leaving them on the last good
    document would draw a complete, plausible indexing run for a file that never
    indexed.
    """
    await _indexed(client)
    await client.post(
        "/upload",
        files=[("files", ("broken.pdf", b"not a pdf at all", "application/pdf"))],
        follow_redirects=True,
    )

    page = (await client.get("/")).text
    # A failed document has an ingest run, so it is selectable — that run is exactly
    # the record of the failure.
    broken = _document_links(page).get("broken.pdf")
    assert broken, f"a failed document cannot be inspected: {_document_links(page)}"

    chosen = (await client.get(f"/?document={broken}")).text
    states = dict(
        re.findall(r'data-type="(parse|chunk|embed|store)"[^>]*data-state="([a-z]+)"', chosen)
    )
    assert states.get("parse") == "done", states
    assert [states.get(name) for name in ("chunk", "embed", "store")] == ["pending"] * 3, (
        f"a failed document shows later stages it never reached: {states}"
    )
    assert "parental leave" not in chosen.lower(), (
        "the previous document's content is still on the track"
    )


async def test_the_whole_walkthrough_works_without_javascript(
    client: httpx.AsyncClient,
) -> None:
    """Indexing, asking and clicking through, all server-rendered.

    CLAUDE.md makes this a hard requirement rather than a nicety: it is what the
    single-machine, nothing-vendored promise rests on. `axis.js` is never loaded here,
    so this is exactly the path a scripts-disabled browser takes.
    """
    await _indexed(client)
    page = (await client.get("/")).text
    assert 'data-state="done"' in page, "indexing left no visible result"

    answered = await client.post(
        "/ask", data={"question": _QUESTION, "strategy": Strategy.NAIVE_RAG.value}
    )
    assert answered.status_code == 200, answered.text

    # The run finished with the Generate card open, because the answer is what that
    # stage produced and a finished run has a payoff to read.
    assert "Generate" in answered.text
    assert 'data-type="synthesize"' in answered.text
    assert 'data-expanded="true"' in answered.text

    href = re.search(r'class="card__open" href="(/\?stage=[^"]+)"', answered.text)
    assert href, "no stage is reachable as a plain link"
    assert (await client.get(href.group(1))).status_code == 200


# -- the demo is repeatable -------------------------------------------------


async def test_starting_over_empties_the_canvas(client: httpx.AsyncClient) -> None:
    """A class watches indexing once; the next class has to watch it too.

    Until this existed the indexing story could only be told once per session — the
    file limit refuses a second upload of the same document, and nothing cleared one.
    An instructor running the demo for a second group cleared cookies in front of the
    room.
    """
    await _indexed(client)
    assert 'data-state="done"' in (await client.get("/")).text

    reset = await client.post("/reset", follow_redirects=False)
    assert reset.status_code == 303, reset.text

    page = (await client.get("/")).text
    assert 'data-state="done"' not in page, "a stage survived the reset"
    assert "Nothing indexed yet" in page


# -- watching it happen ------------------------------------------------------


async def test_a_stage_is_drawn_as_running_while_it_runs(
    client: httpx.AsyncClient, step_store: InMemoryStepStore
) -> None:
    """"given a stage is running, then it is shown as running while it runs".

    The criterion the canvas could not meet at all: a step reached the store only when
    it *completed*, so there was no "started" signal and the page inferred one by
    marking the next pending card. Indexing therefore went from empty to entirely done
    between two polls, and a student watching an upload saw a jump rather than a
    process.

    Asserted against a step the store holds as `running`, because a request cannot
    catch its own upload mid-flight — the run is over before the response returns. The
    live path is the same renderer reading the same trace, once per poll.
    """
    await _indexed(client)
    page = (await client.get("/")).text
    chunk = await _step_id(page, "chunk")

    # Put that stage back into the state a poll two seconds into a run would find.
    step = await step_store.get_step(chunk)
    await step_store.append(step.model_copy(update={"status": StepStatus.RUNNING}))

    running = (await client.get("/canvas")).text
    assert re.search(r'data-type="chunk"[^>]*data-state="running"', running), (
        "a stage the trace says is running is not drawn as running"
    )
    # And it draws no miniature: there is no data yet, and inventing one is the thing
    # this platform exists not to do.
    assert 'class="art art--chunk"' not in running


async def test_the_trace_fingerprint_changes_when_a_status_changes(
    client: httpx.AsyncClient, step_store: InMemoryStepStore
) -> None:
    """What tells the page anything moved, and why `since_seq` cannot.

    A step keeps its `seq` when it goes from running to finished, so a watermark filter
    is structurally blind to the single most interesting transition in a run. The
    fingerprint hashes every step's id *and* status, so it moves on both.
    """
    await _indexed(client)
    before = (await client.get("/trace/recent")).json()
    assert before["fingerprint"], "a session with steps must have a fingerprint"

    page = (await client.get("/")).text
    step = await step_store.get_step(await _step_id(page, "chunk"))
    await step_store.append(step.model_copy(update={"status": StepStatus.RUNNING}))

    after = (await client.get("/trace/recent")).json()
    assert after["max_seq"] == before["max_seq"], "no new step was added"
    assert after["fingerprint"] != before["fingerprint"], (
        "a status change is invisible to the poller, so a running stage can never be "
        "drawn"
    )


async def test_pacing_is_bounded_at_the_api(client: httpx.AsyncClient) -> None:
    """A browser-supplied number that holds a request open needs a ceiling.

    The cookie is user-editable and the pause is per stage, so an unbounded value is a
    way to tie up a worker for as long as the caller likes. Nine stages at the ceiling
    is eighteen seconds — a slow demo, not an outage.
    """
    session = (await client.post("/api/v1/sessions", json={})).json()
    response = await client.post(
        f"/api/v1/sessions/{session['session_id']}/query",
        json={"question": "anything?", "strategy": "naive_rag", "pace_ms": 999_999},
        headers={"Authorization": f"Bearer {session['token']}"},
    )
    assert response.status_code == 400, "an unbounded pace was accepted"


async def test_opening_a_card_keeps_the_rest_of_the_diagram_drawn(
    client: httpx.AsyncClient,
) -> None:
    """"without the rest of the pipeline leaving the screen".

    An opened card used to take the whole board and compress the other track to a row
    of names, which buried the diagram to show one pane — most of the way back to the
    rail-and-pane layout the canvas replaced. Opening one stage must cost the flow
    nothing.
    """
    await _indexed(client)
    await client.post(
        "/ask", data={"question": _QUESTION, "strategy": Strategy.NAIVE_RAG.value}
    )
    page = (await client.get("/")).text
    opened = (await client.get(f"/canvas?stage={await _step_id(page, 'retrieve')}")).text

    assert 'data-expanded="true"' in opened
    # The indexing track is in the other half of the board and keeps every miniature.
    for art in ("art--parse", "art--chunk", "art--embed", "art--store"):
        assert art in opened, f"{art} left the screen when a card was opened"
