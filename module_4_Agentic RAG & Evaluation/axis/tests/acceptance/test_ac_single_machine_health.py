"""PRD Section 5 — instructor must-have:

    "I want the whole system to run reliably on a single machine so that a live
    demo doesn't depend on fragile network or cloud infrastructure."

PRD Section 6 acceptance criterion:

    Given a fresh machine with only API keys configured, when Axis is started,
    then all three layers (Frontend, Backend, AI Backend) come up and pass the
    /api/v1/health check without any external service beyond the configured
    LLM/embedding/search providers.

This is one of the two criteria that must pass at Milestone -1.

The criterion has three clauses, and each gets its own test rather than being
folded into one pass/fail. "All three layers come up" and "without any external
service" are separate claims, and a single assertion on `status == "ok"` would
prove neither of them individually.
"""

from __future__ import annotations

import httpx
import pytest

from ai_backend.contracts.models import Strategy

pytestmark = [
    pytest.mark.story("single-machine reliability"),
    pytest.mark.milestone(-1),
]


async def test_health_is_reachable_without_authentication(
    client: httpx.AsyncClient,
) -> None:
    """Health must answer before a session exists — it is the liveness check."""
    response = await client.get("/api/v1/health")

    assert response.status_code == 200, response.text


async def test_all_three_layers_report_in(client: httpx.AsyncClient) -> None:
    """"All three layers come up" — each named and each reporting for itself.

    Asserted per layer rather than via an aggregate, because an aggregate cannot
    distinguish "all three are healthy" from "one is healthy and the other two
    were never checked".
    """
    body = (await client.get("/api/v1/health")).json()

    reported = {layer["name"]: layer["status"] for layer in body["layers"]}
    assert set(reported) == {"frontend", "backend", "ai_backend"}, (
        f"expected all three layers to report, got {sorted(reported)}"
    )

    # The Frontend and Backend are fully built at Milestone -1 and must be "ok".
    assert reported["backend"] == "ok", reported
    assert reported["frontend"] == "ok", reported

    # The AI Backend is legitimately "degraded" here: the foundation is complete
    # but no strategy pipeline is registered until Milestone 0. It must not be
    # "error" — a red check on a correctly-built foundation would train everyone
    # to ignore the health endpoint.
    assert reported["ai_backend"] in {"ok", "degraded"}, reported


async def test_health_makes_no_external_calls(
    client: httpx.AsyncClient, fake_llm, fake_embeddings
) -> None:
    """"Without any external service" — the shallow check must reach no provider.

    The autouse `_no_real_network` fixture already fails any real socket, so this
    test adds the stronger claim: not even the in-process fakes are touched.
    Health is a question about Axis, and a check that pinged a vendor would report
    Axis as down whenever that vendor was slow — the most expensive way to be
    wrong thirty seconds before a class starts.
    """
    await client.get("/api/v1/health")

    assert fake_llm.call_count == 0, "health must not invoke the LLM provider"
    assert fake_embeddings.call_count == 0, (
        "health must not invoke the embedding provider"
    )


async def test_health_reports_configuration_validity(
    client: httpx.AsyncClient,
) -> None:
    """A valid configuration reports itself valid, with no error text.

    `config_valid` is what makes "only API keys configured" checkable: it is the
    difference between Axis running and Axis being able to answer a question.
    """
    body = (await client.get("/api/v1/health")).json()

    assert body["config_valid"] is True, body.get("config_error")
    assert body["config_error"] is None


async def test_health_reports_which_strategies_are_built(
    client: httpx.AsyncClient,
) -> None:
    """Which strategies can run is enumerable from the health check.

    The point is an instructor confirming both are live *before* a class rather than
    discovering a tool-incapable provider mid-demo. Bounded by the enum rather than a
    literal, so the check cannot claim more strategies exist than do.
    """
    body = (await client.get("/api/v1/health")).json()

    assert "available_strategies" in body
    assert isinstance(body["available_strategies"], list)
    assert len(body["available_strategies"]) <= len(Strategy)


async def test_frontend_shell_renders(client: httpx.AsyncClient) -> None:
    """The Frontend layer serves its page through the same composed process.

    "All three layers come up" includes the one a student actually looks at, so
    the criterion is not met by a healthy API behind a blank page.
    """
    response = await client.get("/")

    assert response.status_code == 200, response.text
    assert "Axis" in response.text
    for label in ("Naive RAG", "Agentic RAG"):
        assert label in response.text, f"{label!r} missing from the strategy selector"


async def test_the_page_offers_exactly_the_strategies_that_exist(
    client: httpx.AsyncClient,
) -> None:
    """Every strategy is named, and nothing else is.

    **Two directions, and the second is the one that rots.** That the built strategies
    appear is easy; that nothing *else* does is what a page quietly gets wrong — a
    cancelled feature survives as a stale label, a dead `{% if %}` branch, or a CSS
    rule naming a value nothing sets. Two graph strategies were once advertised here
    and had to be removed from six places.

    Asserted against the whole rendered document rather than by counting cards, because
    the leak that matters is the text reaching a projector at all. The vocabulary list
    is deliberately broader than the enum: `graph retrieval` was never a `Strategy`
    value, only prose, and prose is what a class reads.
    """
    page = (await client.get("/")).text.lower()

    for strategy in Strategy:
        label = strategy.value.replace("_", " ")
        assert label in page or strategy.value in page, (
            f"{strategy.value!r} exists but is not offered on the page"
        )

    for absent in ("lightrag", "agentic lightrag", "graph retrieval", "graph store"):
        assert absent not in page, f"{absent!r} still appears in the rendered page"


async def test_selecting_a_built_strategy_changes_what_the_page_shows(
    client: httpx.AsyncClient,
) -> None:
    """The selector has to respond to a click without JavaScript.

    A regression guard for a bug the whole suite was blind to. Both the rail's
    selected-card highlight and the main panel's heading were rendered from the
    *server's* idea of the current strategy, so clicking one in the rail checked
    the (visually hidden) radio and changed nothing on screen. The control worked
    perfectly and was indistinguishable from a dead one — reported as "clicking
    Agentic RAG does nothing".

    Assertions on rendered CSS are unusual, and this one earns it: the behaviour is
    entirely presentational, the failure is silent, and every API-level test passed
    throughout. A browser check is the real verification; this is what can run in
    the suite.

    JavaScript is not an option for the fix. HTMX is an optional download, so a
    selector that needed a script would be dead on a fresh checkout — which is why
    `body:has(...)` does the work.

    The mechanism moved when the layout did. It used to reveal a per-strategy header;
    it now reveals the two orchestration stages in the rail, which is the better
    artefact — the difference between the strategies is stated as geometry before
    anything has run, where it previously cost a query to see.
    """
    page = (await client.get("/")).text
    css = (await client.get("/static/app.css")).text

    for value in ("naive_rag", "agentic_rag"):
        assert f'data-strategy="{value}"' in page, value
        assert f'value="{value}"' in page

    # The agentic stages are in the document for every strategy, hidden by CSS. Only
    # rendering the selected one's stages would be the obvious approach and would
    # break this: nothing can re-render on a click that never leaves the browser.
    assert 'data-agentic="true"' in page

    assert ".strategy:has(input:checked)" in css, (
        "the selected-card highlight is server-rendered only — clicking a strategy "
        "will not move it"
    )
    assert 'input[value="agentic_rag"]:checked' in css, (
        "no rule reveals the agentic stages on selection"
    )


@pytest.mark.milestone(2)
async def test_the_ask_fragment_returns_panels_not_a_page(
    client: httpx.AsyncClient,
) -> None:
    """What axis.js swaps in.

    A fragment is only useful if it is a fragment: returning the full document would
    nest a second `<html>` inside the page, and the visible symptom — a duplicated
    header and rail appearing below the answer — would look like a template bug
    rather than a wrong endpoint.

    The other half of the contract is that it renders the *same* template the full
    page includes — `_canvas.html`. Rendering the answer in JavaScript instead would
    mean two renderers that have to keep agreeing about citations, groundedness and
    cost formatting for as long as the project lives.
    """
    session = (await client.post("/api/v1/sessions", json={})).json()
    cookies = {"axis_session": session["session_id"], "axis_token": session["token"]}

    response = await client.post(
        "/ask/fragment",
        data={"question": "Anything at all?", "strategy": "naive_rag"},
        cookies=cookies,
    )

    assert response.status_code == 200, response.text
    body = response.text
    assert "<!doctype" not in body.lower(), "the fragment returned a whole document"
    assert "<html" not in body.lower()
    assert "topbar" not in body, "the fragment must not repeat the page chrome"
    # It is the canvas, with the Generate card opened: the answer is what that stage
    # produced, so it lives there rather than in a panel that had nowhere better to
    # be. A finished run has a payoff to read, which is why the server opens it.
    assert 'class="canvasboard"' in body
    assert 'data-type="synthesize"' in body
    assert 'data-expanded="true"' in body


@pytest.mark.milestone(2)
async def test_a_fresh_page_starts_empty(client: httpx.AsyncClient) -> None:
    """The canvas begins with nothing on it, and says so.

    Deliberate: a student watches it build as things happen, so a fresh page that
    pre-drew a finished-looking pipeline would be claiming work nobody did. Every
    stage is present as a map of what is coming, each card saying what its stage is
    *for*, and every one of them pending.
    """
    page = (await client.get("/")).text

    assert "No answer yet" not in page
    assert 'data-state="pending"' in page, "the canvas should be drawn but unfilled"
    assert 'data-state="done"' not in page, (
        "a fresh session has run nothing — no stage may claim to have completed"
    )
    # Not blank: the shape of RAG, explained, before anything has been spent.
    assert "stands for its meaning" in page
    assert "nothing stored yet" in page


@pytest.mark.milestone(2)
async def test_the_raw_trace_is_reachable_without_javascript(
    client: httpx.AsyncClient,
) -> None:
    """Its own page now, not a disclosure inside a panel and not a tab.

    Still the authenticity guarantee — the canvas is this same data made readable,
    and this is the proof that the readable version is not a story. A plain link to a
    server-rendered page, so it opens with JavaScript disabled.
    """
    session = (await client.post("/api/v1/sessions", json={})).json()
    cookies = {"axis_session": session["session_id"], "axis_token": session["token"]}

    await client.post(
        "/ask/fragment",
        data={"question": "Anything?", "strategy": "naive_rag"},
        cookies=cookies,
    )

    page = (await client.get("/trace", cookies=cookies)).text
    assert 'class="step step--' in page, "the raw step cards are the whole point"
    assert 'href="/trace"' in (await client.get("/")).text, (
        "nothing on the canvas links to the raw trace"
    )
