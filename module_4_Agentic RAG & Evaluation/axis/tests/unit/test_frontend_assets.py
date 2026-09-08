"""The client-side contract: what is served, and what is no longer there.

Unusual tests — they assert on served static files and on template markup. They earn
it because the consumer is a JavaScript file, so nothing on the Python side notices
when the contract between them breaks. Every failure this guards against is silent:
the page renders, the suite passes, and the feature does nothing.

That is not hypothetical. HTMX was gated behind a vendoring check for two milestones
and was never downloaded, so no script ever ran; and the one place it was used pointed
`hx-swap="beforeend"` at an endpoint returning JSON, so it would not have worked if it
had. Both went unnoticed precisely because no test looked here.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from frontend.app import _fingerprint

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = REPO_ROOT / "frontend" / "templates"
STATIC = REPO_ROOT / "frontend" / "static"


async def test_axis_js_is_served(client: httpx.AsyncClient) -> None:
    response = await client.get("/static/axis.js")

    assert response.status_code == 200, response.text
    assert response.text.strip(), "axis.js is empty"


async def test_axis_js_is_loaded_unconditionally(client: httpx.AsyncClient) -> None:
    """No vendoring gate.

    HTMX sat behind `{% if htmx_available %}` and the files were never fetched, so the
    branch was permanently false and the app shipped running no JavaScript at all for
    two milestones. `axis.js` is ours and committed, so there is nothing to check —
    and a gate would recreate exactly that failure.
    """
    page = (await client.get("/")).text

    assert '/static/axis.js' in page
    assert "htmx" not in page.lower(), "HTMX was removed at Milestone 2"


def test_no_template_still_uses_htmx_attributes() -> None:
    """The library is gone, so its attributes are dead markup.

    Left behind they would be invisible: HTMX attributes on a page with no HTMX are
    inert, so a stale `hx-post` looks like a working feature and does nothing. Which
    is the state the narration toggle was already in.
    """
    stale: list[str] = []
    for template in TEMPLATES.glob("*.html"):
        text = template.read_text(encoding="utf-8")
        for attribute in ("hx-post", "hx-get", "hx-target", "hx-swap", "hx-trigger",
                          "sse-connect", "sse-swap", "hx-ext"):
            if attribute in text:
                stale.append(f"{template.name}: {attribute}")

    assert not stale, f"HTMX attributes remain but HTMX is gone: {stale}"


def test_narration_is_wired_through_a_data_attribute() -> None:
    """The replacement is present, not merely the removal.

    A test asserting only that `hx-post` is gone would pass just as happily if
    narration had been deleted along with it.
    """
    trace = (TEMPLATES / "_trace.html").read_text(encoding="utf-8")

    assert "data-narrate=" in trace
    assert "/narrate" in trace


@pytest.mark.parametrize("asset", ["app.css", "axis.js"])
async def test_served_assets_declare_utf8(client: httpx.AsyncClient, asset: str) -> None:
    """Both files contain non-ASCII text, so the charset cannot be left to chance.

    `app.css` uses typographic dashes in comments and `axis.js` renders an ellipsis
    into the page. Served without a declared charset, a browser guesses — and the
    guess that shows mojibake in the UI is a plausible one on a Windows-authored file.

    Asserted on the served response rather than the file, because the encoding that
    matters is the one on the wire. This is the same class of problem as the four
    cp1252 crashes this project has had, one layer out.
    """
    response = await client.get(f"/static/{asset}")

    assert response.status_code == 200
    assert "utf-8" in response.headers.get("content-type", "").lower(), (
        response.headers.get("content-type")
    )
    # And it really does round-trip — a declared charset the bytes do not honour
    # would be worse than none.
    response.text.encode("utf-8")


async def test_trace_recent_filters_by_seq(client: httpx.AsyncClient) -> None:
    """What the canvas polls, and the parameter that keeps runs separate.

    A session accumulates every question's steps, so without `since_seq` a second
    question would fill the canvas with the first one's pipeline before the new run
    had emitted anything — and the canvas cannot tell old steps from new.

    Polling rather than proxying the SSE stream is not a preference. The Frontend
    reaches the Backend through `httpx.ASGITransport`, which buffers a response body
    to completion, so an open-ended stream never yields a line; and the browser
    cannot connect to the Backend directly because `EventSource` cannot set the
    `Authorization` header that route requires. See the route's docstring.
    """
    session = (await client.post("/api/v1/sessions", json={})).json()
    cookies = {"axis_session": session["session_id"], "axis_token": session["token"]}

    # A run, so there is something to poll for.
    await client.post(
        "/ask/fragment",
        data={"question": "Anything?", "strategy": "naive_rag"},
        cookies=cookies,
    )

    everything = (await client.get("/trace/recent", cookies=cookies)).json()["steps"]
    assert everything, "the run recorded no steps"
    assert all(s["seq"] for s in everything), "every step needs a seq to be orderable"

    high = max(s["seq"] for s in everything)
    after = (
        await client.get(f"/trace/recent?since_seq={high}", cookies=cookies)
    ).json()["steps"]

    assert after == [], f"since_seq={high} still returned {len(after)} steps"


async def test_trace_recent_is_empty_before_a_session_exists(
    client: httpx.AsyncClient,
) -> None:
    """The canvas polls on a fresh visit, before any question.

    An empty list rather than a 401 or a 500: nothing has gone wrong, there is simply
    nothing to show, and an error here would put a console full of red in front of
    anyone who opened the page and read nothing.
    """
    response = await client.get("/trace/recent")

    assert response.status_code == 200
    body = response.json()
    assert body["steps"] == []
    assert body["max_seq"] == 0
    # A digest of nothing rather than a sentinel: "no session" and "a session that has
    # done nothing" are the same state to a poller, and giving them the same answer
    # means the client needs no special case for either.
    assert body["fingerprint"] == _fingerprint([])


async def test_the_poller_asks_for_a_digest_not_the_whole_trace(
    client: httpx.AsyncClient,
) -> None:
    """What the canvas polls four times a second, and why it must stay small.

    The canvas needs two things while a run is in flight: has anything changed, and
    where does this run start. That is about fifty bytes. It used to get them from
    `/trace/recent`, which answers by shipping the session's entire trace — every prompt
    and completion of every run — and throwing all of it away.

    The cost is not the bandwidth. Once a response takes longer to build and parse than
    the interval between polls, the next poll starts before the last has finished; a
    browser allows six connections to one host, so the pile-up pushes the `/canvas`
    fetches — the ones that actually redraw the page — behind a queue of trace payloads,
    and the run appears to complete in one jump at the end. It got worse the longer a
    session had been running, which is the worst possible shape for a workshop.
    """
    session = (await client.post("/api/v1/sessions", json={})).json()
    cookies = {"axis_session": session["session_id"], "axis_token": session["token"]}
    for i in range(6):
        await client.post(
            "/ask/fragment",
            data={"question": f"Question {i}?", "strategy": "naive_rag"},
            cookies=cookies,
        )

    digest = await client.get("/trace/state", cookies=cookies)
    full = await client.get("/trace/recent", cookies=cookies)

    assert digest.status_code == 200
    assert set(digest.json()) == {"fingerprint", "max_seq"}, (
        "the polled endpoint must carry nothing the poller does not read"
    )
    assert digest.json()["fingerprint"] == full.json()["fingerprint"]
    # The size of the thing being polled must not grow with the session.
    assert len(digest.content) < 200, len(digest.content)
    assert len(full.content) > 4 * len(digest.content), (
        "the trace is not large enough here for this test to be proving anything"
    )

    js = (await client.get("/static/axis.js")).text
    code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
    assert "/trace/state" in code
    assert "/trace/recent" not in code, "the poller is back on the full trace"
    # And one poll at a time: `setInterval` fires whether or not the last tick has
    # finished, which is how a backlog starts in the first place.
    assert "setInterval" not in code, (
        "polling on an interval lets a slow poll overlap the next one"
    )


def test_the_upload_button_carries_a_spinner() -> None:
    """Upload does seconds of paid work — parse, chunk, embed, index.

    It showed nothing at all while it ran, so the only available reading of a click
    was that it had not registered. Same defect Ask had, in the one other control
    that blocks.
    """
    shell = (TEMPLATES / "base.html").read_text(encoding="utf-8")

    assert 'id="upload-form"' in shell, "axis.js needs a handle on the upload form"
    upload = shell.split('id="upload-form"', 1)[1].split("</form>", 1)[0]
    assert 'class="spinner"' in upload
    assert 'class="button__label"' in upload, (
        "the label needs its own element so the busy text can replace it"
    )


def test_the_upload_button_is_enabled_in_the_markup() -> None:
    """Progressive enhancement, and the one way to get this wrong badly.

    axis.js disables the button until a file is chosen — a spinner for a request that
    returns "no files were included" is worse than no spinner. But that disabling
    must not be *unconditional* in the HTML: with no JavaScript nothing would ever
    re-enable it, and a permanently dead upload button is far worse than a wasted
    round trip.

    The full session is the one exception, and it is a different thing: `full` comes
    from what the session holds, so it can only change on a page load, and there is
    nothing for a script to re-enable. So the rule is not "no `disabled` here" but
    "every `disabled` here is guarded by `full`".
    """
    shell = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    upload = shell.split('id="upload-form"', 1)[1].split("</form>", 1)[0]

    unguarded = [
        line
        for line in upload.splitlines()
        if "disabled" in line and "if full" not in line
    ]
    assert not unguarded, (
        "the upload control is disabled by something other than the file limit — with "
        f"no JavaScript nothing would re-enable it: {unguarded}"
    )


def test_busy_styling_is_shared_rather_than_per_control() -> None:
    """One rule for both blocking controls.

    The spinner layout was keyed to `#ask-button`, so adding it to Upload would have
    rendered an unstyled inline element next to the label. Keyed on containing a
    spinner instead, any future control that blocks gets it for free.
    """
    css = (STATIC / "app.css").read_text(encoding="utf-8")

    assert "button:has(.spinner)" in css
    assert '[data-busy="true"] .spinner' in css
    assert '[data-busy="true"] input[type="file"]' in css, (
        "the file input should dim while its upload is in flight, as the textarea does"
    )


def test_the_palette_is_the_one_the_previous_demo_established() -> None:
    """Axis and module 3 are two demos of one subject, so they share a palette.

    Axis is the second demo this cohort meets. The first —
    `reference/module_3_Enterprise RAG/frontend/styles.css` — established a paper
    theme and a colour language, and a student moving between the two should
    recognise one system rather than two products that happen to teach adjacent
    things.

    Asserted value-by-value rather than "some teal appears somewhere", because the
    failure this guards against is drift back toward a plausible-looking
    near-miss — a palette that is *almost* the same reads as a different product
    more clearly than one that is openly different.

    The strategy pair is the interesting half. Teal/violet is borrowed from module
    3's own Search Lab, which uses exactly that pair for two retrieval engines
    shown side by side. The assertion that `--agentic` is *not* the accent is the
    load-bearing one: making the agentic strategy the platform colour would read as
    the recommended option, and half of what this tool exists to teach is the
    questions on which orchestration is not worth paying for.
    """
    css = (STATIC / "app.css").read_text(encoding="utf-8")

    module_3 = {
        "--paper": "#fcfcf9",
        "--paper-deep": "#f7f7f2",
        "--card": "#ffffff",
        "--ink": "#13343b",
        "--ink-soft": "#0b2429",
        "--ink-muted": "#64747a",
        "--ink-faint": "#8a9699",
        "--rule": "#e4e4dd",
        "--rule-soft": "#efefe8",
        "--rule-strong": "#d3d3ca",
        "--accent": "#20808d",
        "--ok": "#1a7f5a",
        "--warn": "#b4600a",
    }
    for token, value in module_3.items():
        assert re.search(rf"{re.escape(token)}:\s*{re.escape(value)};", css), (
            f"{token} should be {value}, module 3's value for the same role"
        )

    assert re.search(r"--naive:\s*#20808d;", css), "the baseline carries the accent teal"
    assert re.search(r"--agentic:\s*#6d5bd0;", css), (
        "the agentic strategy carries module 3's Search Lab violet"
    )
    assert not re.search(r"--agentic:\s*var\(--accent\)|--agentic:\s*#20808d;", css), (
        "the agentic strategy must not be the platform accent — that reads as the "
        "recommended option, and whether orchestration earns its cost is the "
        "question the tool exists to leave open"
    )

    # One family, distinguished by weight. The display serif that used to be here was
    # the single thing that made the two demos look like different products.
    assert '--font-display: "Inter"' in css
    assert '--font-body: "Inter"' in css
    assert "serif;" in css, "every stack still needs a real system fallback"
    assert not re.search(r"font:\s*400[^;]*var\(--font-display\)", css), (
        "Inter headings need weight 600 — 400 was right for the serif and is "
        "indistinguishable from body text here"
    )


def test_the_structural_label_is_legible_from_the_back_of_a_room() -> None:
    """`.eyebrow` is a heading, so it has to pass contrast like one.

    Axis announces every section with a tracked uppercase label rather than a heavy
    heading — `app.css` says so where `.eyebrow` is defined, and the file's own
    header promises the hierarchy "survives a washed-out beamer and reads from the
    back of a room". At 0.68rem that promise is a contrast requirement.

    The palette has two greys for secondary text, and both are module 3's:
    `--ink-muted` (4.73:1 against the paper, passes AA) and `--ink-faint`
    (2.96:1, fails AA even for large text). The structural label must use the
    first. `--ink-faint` is still correct for what it is named for — placeholders,
    bar fills, brackets, dimmed meta — none of which anyone has to read.

    This is checked because it is the exact thing a palette change breaks quietly:
    the old warm palette had the same fault and measured *worse* (2.69:1), so
    adopting module 3's values improved it without fixing it, and nothing on screen
    would have said so.
    """
    css = (STATIC / "app.css").read_text(encoding="utf-8")

    eyebrow = re.search(r"\.eyebrow \{(.*?)\}", css, re.DOTALL)
    assert eyebrow, ".eyebrow rule not found"
    assert "var(--ink-muted)" in eyebrow.group(1), (
        "the structural label must use --ink-muted (4.73:1), not --ink-faint "
        "(2.96:1, below WCAG AA for any text size)"
    )


def _contrast(a: str, b: str) -> float:
    """WCAG relative-contrast ratio between two `#rrggbb` colours."""

    def luminance(colour: str) -> float:
        raw = colour.lstrip("#")
        channels = [int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        linear = [
            c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    first, second = luminance(a), luminance(b)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def test_every_text_colour_in_the_palette_passes_contrast() -> None:
    """The one property a projected palette cannot be wrong about.

    Computed rather than eyeballed, and asserted against the *paper*, which is the
    lightest ground any of these sits on — passing there means passing on `--card`
    too. `--ink-faint` is excluded and named in the exclusion, because it is a
    deliberate sub-AA tertiary grey and the test above pins the one place that
    mattered.

    Thresholds are WCAG AA: 4.5:1 for body text, 3.0:1 for large. `--warn` lands at
    4.42:1 and is allowed the large-text bar, because it is module 3's value and
    Axis only ever sets it on badges and headings — never on running prose.
    """
    css = (STATIC / "app.css").read_text(encoding="utf-8")

    def token(name: str) -> str:
        found = re.search(rf"{re.escape(name)}:\s*(#[0-9a-fA-F]{{6}});", css)
        assert found, f"{name} is not a literal colour in :root"
        return found.group(1)

    paper = token("--paper")

    for name in ("--ink", "--ink-soft", "--ink-muted", "--accent", "--naive",
                 "--agentic", "--money", "--ok", "--error"):
        ratio = _contrast(token(name), paper)
        assert ratio >= 4.5, f"{name} is {ratio:.2f}:1 on the paper, below AA's 4.5"

    ratio = _contrast(token("--warn"), paper)
    assert ratio >= 3.0, f"--warn is {ratio:.2f}:1, below AA's large-text 3.0"

    # White sits on the two filled strategy chips, which is the only inversion in
    # the stylesheet and the one place `#fff` is hardcoded.
    for name in ("--naive", "--agentic"):
        ratio = _contrast("#ffffff", token(name))
        assert ratio >= 4.5, (
            f"white on a filled {name} chip is {ratio:.2f}:1 — the chip label is the "
            f"strategy's name and has to be readable"
        )


def test_the_theme_is_pinned_light() -> None:
    """No dark mode, and now for two reasons rather than one.

    The first is Axis's own: a half-hearted dark mode looks broken projected, so
    committing to one design beats shipping two and meaning neither. The second
    arrived with the palette — module 3 pins `color-scheme: light` explicitly
    "because it is presented on projectors in bright rooms", and its CLAUDE.md says
    in as many words not to reintroduce a `prefers-color-scheme` block.

    A media query added here would produce a page that looks one way on the
    instructor's laptop and another on a student's, which for a tool whose claim is
    that what you see is what was measured is worse than merely inconsistent.

    `color-scheme: light` is the half that is not about our own rules: without it a
    browser in dark mode paints native form controls and scrollbars dark against
    this ground, so the one part of the page the stylesheet does not own would
    disagree with all of it.
    """
    css = (STATIC / "app.css").read_text(encoding="utf-8")

    # The declaration, not the phrase — the header comment says the words on purpose.
    assert not re.search(r"@media[^{]*prefers-color-scheme", css), (
        "the theme is pinned light on purpose — see the header comment in app.css"
    )
    assert re.search(r"color-scheme:\s*light;", css), (
        "native controls need pinning too, or a browser in dark mode paints them "
        "dark against a paper-white page"
    )


# ---------------------------------------------------------------------------
# The stage walkthrough
# ---------------------------------------------------------------------------
#
# These replaced a block of tests guarding the *old* canvas: a two-column split, a
# vertical node strip, and — most of all — a contract test forcing `_pipeline.html`
# and `axis.js` to use the same class names and wording, because the two rendered the
# same run from opposite sides and had drifted twice.
#
# That contract test is gone because the thing it policed is gone. There is one
# renderer now, on the server, and `axis.js` fetches `/canvas` rather than rebuilding
# any of it. The first test below asserts *that* instead — a structural guarantee
# rather than a promise to keep two files in step by hand.


async def test_only_the_server_renders_stage_content(client: httpx.AsyncClient) -> None:
    """One renderer, enforced.

    `_pipeline.html` and `axis.js` used to draw the same run from two sides and
    drifted twice — first over how repeated retrievals were grouped, then over the
    state attributes that give a reloaded run its colours. Nothing in Python notices,
    because one of the two renderers is a JavaScript file.

    The cards carry far more than those nodes did — chunk text, vectors, similarity
    scores, the assembled prompt, and a miniature of each drawn on the card itself —
    so a second renderer would drift again, and here a drift means a student is
    shown different numbers live than on reload, in a tool whose entire claim is
    that the numbers are real.

    So the guarantee is architectural: the script fetches rendered HTML and swaps it
    in. This fails the moment it starts building stage content itself.
    """
    js = (await client.get("/static/axis.js")).text
    code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)

    assert "/canvas" in code, "the canvas must be fetched, not rebuilt"

    # The vocabulary of stage content belongs to the templates. Any of it appearing
    # in the script means something is being rendered twice again.
    for token in (
        "vector_head",
        "candidates",
        "chunkview",
        "sub_questions_text",
        "scores__item",
        "overlap_with_previous",
        "vector_strip",
        "total_in_index",
    ):
        assert token not in code, (
            f"{token!r} is stage content and appears in axis.js — the second "
            f"renderer is back"
        )


async def test_the_workspace_fits_the_viewport(client: httpx.AsyncClient) -> None:
    """No page scroll at the size a class is watching.

    A room cannot scroll. The page is exactly the viewport; the canvas fits inside it
    and only an opened card scrolls, being the one place whose content genuinely
    varies in length.
    """
    css = (await client.get("/static/app.css")).text

    assert "html, body { height: 100%; overflow: hidden; }" in css
    # `100dvh` rather than `100vh`: on mobile browsers `vh` counts retracting chrome,
    # so the layout would sit permanently cut off behind the address bar.
    assert "100dvh" in css
    assert "--topbar-h" in css, (
        "the workspace is sized as the viewport minus the topbar, so that height has "
        "to be a fixed value rather than whatever the content happens to be"
    )
    assert "@media (min-width: 900px)" in css, (
        "the no-scroll rules must be gated — a no-scroll layout on a phone is a "
        "broken layout"
    )


async def test_the_canvas_shows_both_phases_of_rag(client: httpx.AsyncClient) -> None:
    """Indexing and answering, as two tracks of one diagram, in the order they run.

    The Naive RAG notebook frames the subject exactly this way — "Phase A — Indexing,
    done once, upfront" then "Phase B — Query" — and a student arriving from it should
    recognise the shape. Separate screens would hide the fact that makes retrieval
    work: the same model and the same vector space on both sides.

    The index band between the tracks is what carries that across. It is the object
    both phases touch, and without it nothing on screen says the second track reads
    what the first one wrote.
    """
    page = (await client.get("/")).text

    for stage in ("parse", "chunk", "embed", "store", "retrieve", "augment", "synthesize"):
        assert f'data-type="{stage}"' in page, f"{stage!r} missing from the canvas"

    assert 'class="track track--index"' in page
    assert 'class="track track--query"' in page
    assert 'class="indexband"' in page


async def test_selecting_a_strategy_reveals_its_extra_stages(
    client: httpx.AsyncClient,
) -> None:
    """The selector has to respond to a click without JavaScript.

    A regression guard for a bug the whole suite was once blind to: the selection was
    rendered from the *server's* idea of the current strategy, so clicking a strategy
    checked the (visually hidden) radio and changed nothing on screen. The control
    worked perfectly and was indistinguishable from a dead one.

    The mechanism moved with the layout. It used to reveal a per-strategy header; it
    now reveals the two orchestration cards on the answering track — better anyway,
    because it states the orchestration difference as geometry before anything has
    run, and that previously cost a query to see.

    So the agentic stages must be *in* the document and hidden by CSS. Rendering only
    the selected strategy's stages would be the obvious approach and would break this:
    nothing can make the server re-render on a click that never leaves the browser.
    """
    page = (await client.get("/")).text
    css = (await client.get("/static/app.css")).text

    assert 'data-agentic="true"' in page, (
        "the agentic stages must be rendered even when a single-shot strategy is "
        "selected, or the selector cannot reveal them without a round trip"
    )
    for value in ("naive_rag", "agentic_rag"):
        assert f'value="{value}"' in page, value

    assert '.cardslot[data-agentic="true"] { display: none; }' in css
    assert 'input[value="agentic_rag"]:checked' in css, (
        "no rule reveals the agentic stages on selection"
    )
    # Numbering must come from a counter, or hiding two stages leaves 01 02 03 04 07.
    assert "counter-reset: stage" in css
    assert "counter-increment: stage" in css


async def test_the_other_readings_are_their_own_pages(
    client: httpx.AsyncClient,
) -> None:
    """Compare and the raw trace are links, not tabs beside the canvas.

    They were radios revealed by `body:has()`, which worked and was the wrong shape:
    a switcher makes the canvas one option among four when the canvas is what the
    product is. Both span more than the run on screen — Compare spans two strategies,
    the raw trace spans every step of it — so neither is a view *of* the pipeline.

    Pages rather than tabs, and still server-rendered, which is the property the
    radios were chosen for in the first place.
    """
    page = (await client.get("/")).text

    assert 'name="view"' not in page, "the view switcher is back"
    assert 'href="/compare"' in page
    assert 'href="/trace"' in page

    for path in ("/compare", "/trace"):
        response = await client.get(path)
        assert response.status_code == 200, path
        assert "<!doctype" in response.text.lower(), f"{path} is not a whole page"


async def test_the_run_controls_belong_to_the_run_page(
    client: httpx.AsyncClient,
) -> None:
    """**The rule is "no control that cannot act", and it was never "no rail".**

    That distinction is the whole of this test. The strategy radios carry
    `form="ask-form"`, and the ask form is only on the Run page — so anywhere else they
    were controls that looked live, moved their own highlight when clicked, and could
    not act on anything. Upload and pace are the same shape: they set a run up, on pages
    that read runs which have already happened.

    The rail itself is on every page now, because two of its groups *can* act
    everywhere: the corpus toggle decides what every page is showing you, and the layer
    readout is not a control at all. Asserting the rail's absence was the shorthand that
    hid the real rule; this asserts the rule.

    The nav name goes with it. The links are readings of one subject, and naming the
    first after the surface it draws on made it the odd one out.
    """
    run = (await client.get("/")).text

    assert 'class="rail"' in run, "the run has lost its controls"
    assert 'form="ask-form"' in run, "the strategy radios are not bound to the ask form"
    assert ">Run</a>" in run, "the first nav link should name the run, not the canvas"

    for path in ("/compare", "/trace", "/summarize", "/why-agentic"):
        page = (await client.get(path)).text
        # The rule: nothing that submits to a form this page does not have.
        assert 'form="ask-form"' not in page, (
            f"{path} carries a control bound to the ask form, which is not on it"
        )
        assert 'name="strategy"' not in page, (
            f"{path} offers a strategy radio bound to a form that is not on the page"
        )
        assert 'href="/"' in page, f"{path} offers no way back to the run"

        # The positive half. Both of these can act here, and a rail that renders on a
        # page without them would be a frame around nothing.
        assert 'class="rail"' in page, f"{path} lost the rail entirely"
        assert 'action="/corpus"' in page, (
            f"{path} cannot switch corpus, so what it is showing can only be changed "
            f"from another page"
        )
        assert 'class="layers"' in page, f"{path} lost the health readout"

    # Upload belongs where documents are chosen or run against. Not on Compare or the
    # raw trace, which read runs that have already finished — a document uploaded there
    # changes nothing on screen.
    for path in ("/compare", "/trace"):
        page = (await client.get(path)).text
        assert 'action="/upload"' not in page, f"{path} offers an upload with no run"
    for path in ("/", "/summarize"):
        page = (await client.get(path)).text
        assert 'action="/upload"' in page, (
            f"{path} chooses among documents but cannot add one"
        )

    # Pace animates the canvas, and only the Run page has one.
    for path in ("/compare", "/trace", "/summarize", "/why-agentic"):
        page = (await client.get(path)).text
        assert 'action="/pace"' not in page, (
            f"{path} offers slow motion with nothing to watch"
        )


async def test_summarizing_is_a_page_rather_than_a_control_in_the_rail(
    client: httpx.AsyncClient,
) -> None:
    """The most expensive action Axis offers should not be a side effect of the rail.

    It was a button under the document list: one click read every document a student
    had uploaded, with no choice of documents and no confirmation. And its result was
    reachable only by pressing it again, so opening the trace to show the map-reduce
    steps lost the summary you went there to explain.

    It also belongs beside Run rather than filed under setup. Summarizing is the
    *contrast* that justifies retrieval — read everything, or read the relevant part —
    and the nav is where the two sit at the same level.
    """
    await client.post("/demo-documents", follow_redirects=True)
    run = (await client.get("/")).text

    assert 'href="/summarize"' in run, "the nav does not reach the summarize page"
    assert 'action="/summarize"' not in run, (
        "the rail still runs the summarizer directly — it reads every document on one "
        "click, with no choice and no way back to the result"
    )

    page = (await client.get("/summarize")).text
    assert 'action="/summarize"' in page, "the page offers no way to run a summary"
    assert 'type="checkbox" name="documents"' in page, (
        "the page offers no choice of documents"
    )


async def test_every_browser_call_goes_through_the_frontend(
    client: httpx.AsyncClient,
) -> None:
    """Not straight at the API, which the browser cannot authenticate to.

    `data-narrate` pointed at `/api/v1/sessions/{id}/trace/{step}/narrate`, which
    requires `Authorization: Bearer <token>` — and the token lives in an `httponly`
    cookie precisely so no script can read it. So every narration request from the
    page was a 401, while the acceptance test passed the header itself and stayed
    green throughout. The same class of bug as the HTMX attributes that never ran:
    a feature that worked at the layer it was tested at and nowhere a student was.
    """
    js = (await client.get("/static/axis.js")).text
    page = (await client.get("/")).text

    assert "/api/v1/" not in js, (
        "the browser cannot set the Authorization header the API requires — every "
        "call must go through a Frontend route that reads the session cookie"
    )
    assert "/api/v1/" not in page, (
        "a template is pointing the browser at the authenticated API directly"
    )
    assert "/narrate/" in js


async def test_the_demo_corpus_is_off_by_default(settings) -> None:
    """Four documents through a real embedding provider, on a click, in a sidebar.

    On the fake providers it is free; on a real one it is a paid round trip per file,
    and the button sat where a curious student would find it — twice, on two sessions,
    in a room of twenty. Off is the default; `AXIS_DEMO__DOCUMENTS_ENABLED=true` brings
    it back.

    Asserted against `Settings` rather than the page, because the suite's own fixture
    turns it *on* — the corpus is what the labelled predictions were measured against,
    so the tests have to be able to index it. That inversion is exactly why the default
    needs a test of its own.
    """
    from ai_backend.config.settings import Settings

    assert Settings().demo.documents_enabled is False
    assert settings.demo.documents_enabled is True, (
        "the suite needs the corpus; if this flips, the predicted-outcome tests are "
        "silently measuring nothing"
    )


async def test_the_labelled_questions_need_their_own_corpus(
    client: httpx.AsyncClient,
) -> None:
    """A prediction is a claim about specific documents.

    "Splitting this question finds a document the blended search misses" is true of the
    demo corpus and of nothing else, so offering these beside somebody's own unrelated
    PDFs would have the platform confidently predicting outcomes nothing measured.

    They appear once that corpus is indexed and not before — which, with the demo set
    off by default, means they are absent on a normal install.
    """
    assert 'class="prediction"' not in (await client.get("/")).text

    await client.post("/demo-documents", follow_redirects=True)
    assert 'class="prediction"' in (await client.get("/")).text


async def test_the_pace_control_works_without_javascript(
    client: httpx.AsyncClient,
) -> None:
    """Slow motion is a form post, like every other control here.

    It exists because some stages are genuinely instantaneous — parsing and chunking
    are a few milliseconds of local work — so no polling interval makes them visible
    and a class still has to see them happen. The pause goes *between* stages, so the
    canvas has to say so: a delay a viewer cannot see is one they will read into the
    durations beside it.
    """
    page = (await client.get("/")).text
    assert 'action="/pace"' in page
    assert 'name="pace_ms"' in page

    response = await client.post("/pace", data={"pace_ms": "600"}, follow_redirects=True)
    assert response.status_code == 200
    assert "paced for teaching" in response.text
    assert "every timing and cost shown is measured" in response.text, (
        "a paced canvas must say the timings on it are still real"
    )


async def test_the_pace_cookie_cannot_hold_a_request_open(
    client: httpx.AsyncClient,
) -> None:
    """The cookie is user-editable and decides how long a request runs.

    Clamped in the Frontend so a nonsense value is corrected rather than round-tripped
    into a validation error in front of a class, and clamped again at the API so the
    correction is not the only thing standing between a hand-written cookie and a tied
    up worker.
    """
    response = await client.post(
        "/pace", data={"pace_ms": "600000"}, follow_redirects=False
    )
    assert "axis_pace=2000" in response.headers.get("set-cookie", "")


async def test_narration_is_wired_on_the_trace_page(client: httpx.AsyncClient) -> None:
    """The control has to be reachable on every page that renders one.

    It was not. `wireNarration` was called from inside `enhance()`, which bails on any
    page without a canvas — so from the moment Compare and Trace became their own pages,
    the "Narrated" disclosure on the raw trace opened and stayed empty.

    That is the second time this one feature has broken for a structural reason rather
    than a logical one: before this it pointed at `/api/v1`, which the browser cannot
    authenticate to because the token is in an `httponly` cookie. Both failures looked
    identical from the outside — a control that opens and does nothing — and neither was
    visible to the acceptance test, which calls the API directly and passes the header
    itself.

    So this asserts the two halves that have each been missing once: the markup offers
    the control, and the script wires it from the document rather than from a canvas
    that is not on this page.
    """
    session = (await client.post("/api/v1/sessions", json={})).json()
    cookies = {"axis_session": session["session_id"], "axis_token": session["token"]}
    await client.post(
        "/ask/fragment",
        data={"question": "Anything?", "strategy": "naive_rag"},
        cookies=cookies,
    )

    page = (await client.get("/trace", cookies=cookies)).text
    assert "data-narrate=" in page, "the trace page offers no narration control"

    js = (await client.get("/static/axis.js")).text
    code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
    assert "wireNarration(document)" in code, (
        "narration is wired from the canvas only, so it is dead on every other page"
    )


async def test_every_slow_button_shows_that_it_is_working(
    client: httpx.AsyncClient,
) -> None:
    """Five forms post natively and spend real money. Each has to say so while it does.

    Every one of these was silent on click, and two of them silently: `Load the demo set`
    and `Summarize` each carried a `.spinner` in the markup that no code ever turned on,
    because the wiring knew one hard-coded selector. Loading the demo set is five paid
    embedding round trips; summarizing is one LLM call per document plus one to combine.

    So the opt-in is declarative — a form carries `data-busy-label`, which is also the
    word it shows — and this asserts the three halves that have each been the missing one
    somewhere in this file's history: the label hook, the spinner it reveals, and a
    `.button__label` for the script to swap.
    """
    # Before the set is loaded, because that button hides once the demo corpus is full.
    await _assert_declares_busy(client, {"/": ["/demo-documents"]})

    await client.post("/demo-documents", follow_redirects=True)
    await _assert_declares_busy(
        client,
        {
            "/": ["/corpus/clear", "/reset"],
            # `?point=`, because a bare Why page now opens with all four cards closed and
            # therefore no run form at all — the form belongs to the open card.
            "/why-agentic?point=compare": ["/why-agentic/"],
            "/summarize": ["/summarize"],
        },
    )

    # The spinner has to be *in* each of those buttons, not merely defined in the CSS.
    #
    # One pain point at a time, because only the open card carries a form now — the other
    # three are the overview. Counting on a single page would silently only ever check
    # whichever card happens to be first.
    for point in ("summarize", "compare", "infer", "remember"):
        why = (await client.get(f"/why-agentic?point={point}")).text
        forms = why.count("data-busy-label=")
        assert forms == 1, f"{point}: expected exactly one run form, found {forms}"
        assert why.count('class="spinner"') >= forms, (
            f"{point}: the run button carries no spinner, so a run in flight shows "
            f"nothing"
        )
        assert why.count('class="button__label"') >= forms, (
            f"{point}: the label is not in its own span, so the script has nothing to "
            f"swap"
        )


async def test_the_busy_state_is_wired_and_does_not_capture_the_post(
    client: httpx.AsyncClient,
) -> None:
    """Wired from the document, and it must never intercept the submit.

    From the document because `enhance()` bails on any page without a canvas, and none
    of these five pages except Run has one — that is how the narration control came to be
    dead on two pages without anyone noticing.

    No `preventDefault` because these forms have no fetch behind them: the native post is
    what runs the work. Intercepting it would make the most expensive actions in the
    product depend on a script having loaded, which is the hard requirement in CLAUDE.md
    broken in the worst possible place.
    """
    home = await client.get("/")
    js = (await client.get(_asset_path(home, "axis.js"))).text
    code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)

    assert "wireBusyForms(document)" in code, (
        "the busy forms are wired from the canvas only, so the state is dead on every "
        "page that has one"
    )
    body = code.split("function wireBusyForms", 1)[1].split("\nfunction ", 1)[0]
    assert "preventDefault" not in body, (
        "the busy state intercepts the native post, so these forms now need JavaScript"
    )


def test_the_busy_button_is_not_faded_while_it_spins() -> None:
    """The regression that made a correct implementation look broken.

    `button[disabled] {{ opacity: 0.35 }}` says "not now", which is right for a control
    that cannot act. A *busy* button is disabled for a different reason — to stop a
    second click landing on work already in flight — and fading it composites the
    spinner down with it, to a few per cent of contrast. That was true of every spinner
    in the product, not only the one it was noticed on: Ask and Upload disable their own
    buttons too.

    Asserted on the stylesheet because nothing on the Python side notices when a CSS
    rule goes missing, and the symptom is "the feature does nothing" rather than an
    error.
    """
    css = (STATIC / "app.css").read_text(encoding="utf-8")

    assert re.search(
        r'\[data-busy="true"\]\s+button\[disabled\]\s*\{[^}]*opacity:\s*1', css
    ), (
        "nothing un-fades the busy button, so its spinner is composited at 35% and is "
        "effectively invisible"
    )
    # And the ring takes the button's own colour, so it is visible on the ghost buttons
    # too — `Load the demo set`, `Clear this corpus` and `Start over` are all ghosts, and
    # a hard-coded white ring on those is no ring at all.
    ring = re.search(r'\[data-busy="true"\]\s+\.spinner\s*\{([^}]*)\}', css)
    assert ring and "currentColor" in ring.group(1), (
        "the spinner ring is a fixed colour, so it is invisible on a ghost button"
    )


def test_the_rail_can_actually_scroll() -> None:
    """`overflow-y: auto` was inert for as long as it existed, and nothing noticed.

    `.rail` carried `align-self: start`, which beats the shell's `align-items: stretch`,
    so the rail was sized by its content rather than by the grid row — and an
    auto-overflow box whose used height equals its content height never produces a
    scrollbar. `html, body { overflow: hidden }` then clipped the excess at the viewport
    with no scroll available anywhere, so the bottom of the rail was simply unreachable.

    Asserted as "the overflow declaration is accompanied by a height bound", because the
    declaration on its own is exactly the state that looked correct and did nothing.
    """
    # Comments stripped first: the rule below explains, by name, the declaration it
    # removed, so a search for that declaration matches the sentence saying it is gone.
    css = _without_comments((STATIC / "app.css").read_text(encoding="utf-8"))

    rule = re.search(r"\.shell\s*>\s*\.rail\s*\{([^}]*)\}", css)
    assert rule, "the rail has no overflow rule at all"
    declarations = rule.group(1)
    assert "overflow-y: auto" in declarations
    assert "align-self: stretch" in declarations and "min-height: 0" in declarations, (
        "the rail scrolls only if the grid row bounds its height; `overflow-y` alone is "
        "inert and hides everything below the fold"
    )
    assert not re.search(r"\.rail\s*\{[^}]*align-self:\s*start", css), (
        "`align-self: start` on .rail unbounds its height again"
    )


async def test_the_why_page_fills_its_column(client: httpx.AsyncClient) -> None:
    """`.page`'s 74rem cap left ~464px dead to the right at 1920px.

    Right for Summarize, whose content is a narrow picker over a prose summary. Wrong for
    Why agentic, whose payload is a two-column comparison of two strategies being
    squeezed to fit inside a cap meant for running text.
    """
    page = (await client.get("/why-agentic")).text
    assert "page page--wide" in page, "the why page is still capped at .page's max-width"

    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert re.search(r"\.page--wide\s*\{[^}]*max-width:\s*none", css)
    # The pane fills; the prose inside it does not. A 200-character line is unreadable
    # however much room there is for it.
    #
    # `.painpoint__measured` rather than `.painpoint__symptom`: the symptom moved onto
    # the card face, where the four-column grid track is the cap and an explicit one
    # would fight it. The detail pane is the full-width thing now, and this is its
    # longest line of running text.
    assert re.search(r"\.painpoint__measured\s*\{[^}]*max-width:", css), (
        "the detail pane fills the column but its prose runs the full width with it"
    )


def test_the_why_page_scrolls_its_detail_and_not_itself() -> None:
    """The four cards stay on screen because the scroll is one level down.

    A run produces two full answers, ~500px of them, and if that landed in the page's own
    scroll it would push the row of four off the top — undoing the whole point of the
    row. So `.page--fit` takes `overflow: hidden` and the detail pane takes the scroll.

    Both halves are asserted, for the reason the rail taught last round: `overflow-y:
    auto` on a box with no height bound above it is *inert*, and looks completely
    correct while doing nothing. `min-height: 0` is the bound — a flex item's automatic
    minimum size is its content, so without it the pane grows instead of scrolling.
    """
    css = _without_comments((STATIC / "app.css").read_text(encoding="utf-8"))

    fit = re.search(r"\.page--fit\s*\{([^}]*)\}", css)
    assert fit and "overflow: hidden" in fit.group(1), (
        "the page still owns the scroll, so a result pushes the four cards off screen"
    )
    assert "flex-direction: column" in fit.group(1)

    # **Two levels down now, and the whole chain has to be complete.** The detail moved
    # inside the card it describes, so the height passes page -> row -> open card ->
    # detail, and a break anywhere along it leaves the `overflow-y` at the end inert.
    #
    # Each selector's declarations are pooled across its rules, because the base rule and
    # the one inside the 1280px query legitimately split them — which of the two carries
    # a given declaration is not what this test is about.
    def declarations(selector: str) -> str:
        found = re.findall(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", css)
        assert found, f"`{selector}` has no rule at all"
        return " ".join(found)

    row = declarations(".painpoints")
    assert "flex: 1" in row and "min-height: 0" in row, (
        "the card row does not take the page's remaining height, so the open card has no "
        "bound to scroll within and a long result grows the row and pushes the page"
    )

    detail = declarations(".painpoint__detail")
    for declaration in ("flex: 1", "min-height: 0", "overflow-y: auto"):
        assert declaration in detail, (
            f"the open card's detail is missing `{declaration}`; without all three the "
            f"scroll is either absent or inert"
        )

    assert ".painpoint-detail" not in css, (
        "the old page-level detail section is still styled, so it is probably still "
        "rendered below the row — which is the thing this redesign removed"
    )


def test_the_open_card_stays_wide_enough_for_two_answers_side_by_side() -> None:
    """Two numbers that are one decision, and they drift apart silently.

    The result renders inside a card that is a fraction of the page column now, not all
    of it. `.painpointslot[data-open]`'s grow factor sets that fraction, and `.versus`'s
    `minmax` floor sets how narrow two columns may get before they collapse to one — and
    a collapsed `.versus` is naive stacked above agentic, which is not a comparison.

    At a 1440px window the page column is ~1070px after the rail and its padding. With
    `flex: 4` against three cards at `flex: 1`, the open card gets 4/7 of it, ~611px, so
    the floor has to be at or below ~17rem for two columns to survive. Raise the floor or
    lower the grow factor and the comparison silently stacks on the smaller of the two
    screens this is taught on, with every other test still green.
    """
    css = _without_comments((STATIC / "app.css").read_text(encoding="utf-8"))

    grow = re.search(
        r'\.painpointslot\[data-open="true"\]\s*\{[^}]*flex:\s*(\d+)', css
    )
    assert grow, "the open card has no grow factor, so it does not widen in place"
    assert int(grow.group(1)) >= 4, (
        f"the open card grows by {grow.group(1)} against three cards at 1, which leaves "
        f"it too narrow at 1440px for two answer columns"
    )

    floor = re.search(r"\.versus\s*\{[^}]*minmax\(min\(100%,\s*(\d+)rem\)", css)
    assert floor, "`.versus` has no column floor, so its stacking point is unknown"
    assert int(floor.group(1)) <= 17, (
        f"`.versus` collapses to one column below {floor.group(1)}rem, which the open "
        f"card cannot clear at a 1440px window — the two answers would stack"
    )


async def test_assets_are_fingerprinted(client: httpx.AsyncClient) -> None:
    """A fix a browser does not fetch is not a fix.

    Both assets were linked as bare paths and served by a stock `StaticFiles` mount,
    which sends `ETag` and `Last-Modified` and no `Cache-Control` — so a browser may
    apply heuristic freshness and keep the copy it has. A stale `axis.js` produces a page
    where a just-written feature does nothing while every server-side test passes, which
    is indistinguishable from a real bug and cost a full diagnosis once already.

    A content hash rather than a timestamp, so a restart with no edit keeps the cache
    warm and an edit invalidates exactly the file that changed.
    """
    page = (await client.get("/")).text

    for name in ("app.css", "axis.js"):
        match = re.search(rf"/static/{re.escape(name)}\?v=([0-9a-f]+)", page)
        assert match, f"{name} is linked without a version, so a fix may not be fetched"
        served = await client.get(match.group(0))
        assert served.status_code == 200, served.text

    # The hash tracks the bytes. Two renders of the same file give the same URL.
    again = (await client.get("/compare")).text
    pattern = r"/static/app\.css\?v=([0-9a-f]+)"
    assert re.search(pattern, page).group(1) == re.search(pattern, again).group(1), (
        "the asset version changes between renders, so nothing is ever cached"
    )


def _asset_path(response: httpx.Response, name: str) -> str:
    """The versioned URL a page links for one asset, so a test fetches what a browser does."""
    match = re.search(rf"/static/{re.escape(name)}(\?v=[0-9a-f]+)?", response.text)
    assert match, f"{name} is not linked on this page"
    return match.group(0)


def _without_comments(css: str) -> str:
    """CSS with its comments removed.

    Needed because the comments in `app.css` explain the declarations they replaced, by
    name — so a test asserting a declaration is *absent* otherwise matches the sentence
    saying it was taken out.
    """
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


async def _assert_declares_busy(
    client: httpx.AsyncClient, expected: dict[str, list[str]]
) -> None:
    """Every named form on every named page carries `data-busy-label`."""
    for path, actions in expected.items():
        page = (await client.get(path)).text
        for action in actions:
            forms = [
                f for f in re.findall(r"<form[^>]*>", page) if f'action="{action}' in f
            ]
            assert forms, f"{path} renders no form posting to {action}"
            for form in forms:
                assert "data-busy-label=" in form, (
                    f"{path}: the form posting to {action} spends real money and "
                    f"declares no busy label, so it is silent on click:\n  {form}"
                )
