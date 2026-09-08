"""Frontend application — Jinja2 templates, plus one small hand-written script.

Server-rendered rather than a JavaScript SPA, and that is a teaching decision as
much as a technical one: the interesting thing in Axis is the trace and the
comparison, not a build pipeline.

HTMX used to be named here as the mechanism for the live trace. It was removed at
Milestone 2, having never worked — the files were gated behind `_vendored` and were
never downloaded, so no script had ever run in this app, and the one place HTMX was
used would have swapped a JSON response into the DOM. `static/axis.js` replaces it:
no framework, no build step, and `EventSource` plus `fetch` are all it needs.

Every route here renders fully without that script. `/ask` is the native form post
and `/ask/fragment` is the same work rendered for in-place swapping; the second is a
strict enhancement of the first.

This layer talks to the Backend over HTTP through `BackendClient` and imports
nothing from `backend` or `ai_backend` beyond narrowed, secret-free config.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import httpx
from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from ai_backend.config.settings import FrontendSettings, Settings, for_frontend, get_settings
from ai_backend.contracts.models import Strategy
from ai_backend.contracts.pipeline import CORPORA, DEFAULT_CORPUS, DEMO_CORPUS
from frontend.api_client import BackendClient

logger = logging.getLogger("axis.frontend")

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

# Inter, vendored rather than loaded from a CDN — see static/VENDOR.md. Module 3
# pulls the same family from Google Fonts; Axis cannot, because PRD Section 5 puts
# the whole system on one machine with no network dependency.
#
# Every CSS font stack has a real system fallback, so an absent file degrades to the
# platform sans rather than to nothing — but it degrades *visibly*, via a setup
# banner, because a silently approximated design is one nobody ever gets round to
# fixing.
#
# Only the two weights the page actually leans on are checked. SemiBold is listed in
# VENDOR.md and used by headings, but a missing 600 synthesises acceptably from 500,
# whereas a missing body face changes every line of the page.
#
# This is now the only vendoring gate. `axis.js` is ours and committed, so it is
# loaded unconditionally; the HTMX pair that used to be checked here was never
# downloaded, which meant the app shipped for two milestones running no script at all.
_FONT_FILES = ("fonts/Inter-Regular.woff2", "fonts/Inter-Medium.woff2")


def _vendored(files: tuple[str, ...]) -> bool:
    return all((STATIC_DIR / name).is_file() for name in files)


# Content hashes for the served assets, computed on first use and held for the process.
#
# **This exists because a fix that a browser does not fetch is not a fix.** `app.css` and
# `axis.js` were linked as bare paths and served by a stock `StaticFiles` mount, which
# sends `ETag` and `Last-Modified` and no `Cache-Control` — so a browser is free to apply
# heuristic freshness and keep serving the copy it already has. A stale `axis.js` produces
# a page where a just-written feature does nothing, while every server-side test passes:
# indistinguishable from a real bug, and it cost a full diagnosis once already.
#
# A hash rather than a timestamp or a startup token, so the URL changes when the *bytes*
# change and never otherwise. A restart with no edit keeps the cache warm, and an edit
# invalidates exactly the file that changed.
_ASSET_HASHES: dict[str, str] = {}


# Inline markdown, and only inline. Models write "**Net 45**" whether or not you ask
# them to, and rendering that as literal asterisks made every answer look like it had
# been pasted out of a terminal.
#
# **Escaped first, then decorated.** The answer is LLM output derived from uploaded
# documents — untrusted input, System Design Section 6.5 priority 4 — so the text is
# HTML-escaped *before* any of these patterns run. The patterns then only ever insert
# tags around already-inert text, which means no markup the model emits can survive as
# markup. Reaching for a markdown library instead would have meant auditing its HTML
# passthrough, and every library has one.
#
# Block syntax is deliberately absent: no headings, no lists, no links. `pre-wrap` in
# the stylesheet already preserves the line structure, so a model's "- item" reads as a
# bullet without anything parsing it, and a link is the one construct that could carry
# a destination a reader might click.
_MD_CODE = re.compile(r"`([^`\n]+)`")
_MD_BOLD = re.compile(r"\*\*(\S(?:[^*]*\S)?)\*\*")
# `*` only. `_italic_` is not supported on purpose: contract text and filenames carry
# underscores in the middle of words, and a rule that turns `acme_msa_2026` into
# emphasis is worse than no emphasis at all.
_MD_ITALIC = re.compile(r"(?<![\w*])\*(\S(?:[^*]*\S)?)\*(?![\w*])")
_MD_STASH = re.compile(r"\x00(\d+)\x00")


def _inline_markdown(text: str | None) -> Markup:
    """Bold, italic and inline code, over text that has already been made inert."""
    out = str(escape(text or ""))

    # Code spans are lifted out before the emphasis rules run, so `**` inside a code
    # span stays literal — which is the whole point of a code span.
    spans: list[str] = []

    def stash(match: re.Match[str]) -> str:
        spans.append(match.group(1))
        return f"\x00{len(spans) - 1}\x00"

    out = _MD_CODE.sub(stash, out)
    # Bold before italic: `**x**` would otherwise be read as an italic `*` wrapping
    # `*x*`, and the answer would come out with stray asterisks inside emphasis.
    out = _MD_BOLD.sub(r"<strong>\1</strong>", out)
    out = _MD_ITALIC.sub(r"<em>\1</em>", out)
    out = _MD_STASH.sub(lambda m: f"<code>{spans[int(m.group(1))]}</code>", out)
    return Markup(out)


# The reasons offered for a wrong answer. A closed list rather than a free-text box
# alone, because "it was wrong" is not actionable and the four ways an answer here can
# be wrong are genuinely different repairs: the retrieval missed, the retrieval was
# fine and the prose is not supported by it, the answer is right as far as it goes, or
# it refused something the documents do answer. Which one it is decides whether you
# open Search or Generate in the trace, so asking costs the reporter one click and
# saves the reader the whole run.
FEEDBACK_REASONS = (
    ("contradicts", "Wrong — it contradicts the documents"),
    ("unsupported", "Unsupported — the citation does not say this"),
    ("incomplete", "Incomplete — it missed part of the answer"),
    ("refused", "It declined, but the documents do answer this"),
)
FEEDBACK_REASON_IDS = frozenset(value for value, _ in FEEDBACK_REASONS)


def _asset_url(name: str) -> str:
    """`/static/<name>?v=<hash>` — the path a template should link.

    Falls back to the bare path if the file is missing rather than raising: a checkout
    without `static/` already degrades to a page that says so (see `create_app`), and a
    template crash would be a worse way to learn it.
    """
    if name not in _ASSET_HASHES:
        path = STATIC_DIR / name
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        except OSError:
            return f"/static/{name}"
        _ASSET_HASHES[name] = digest
    return f"/static/{name}?v={_ASSET_HASHES[name]}"


def create_app(
    *,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    backend_base_url: str | None = None,
    shared_state: object | None = None,
) -> FastAPI:
    """Build the Frontend ASGI app.

    `shared_state` is the root app's `state`, when mounted. The Frontend records
    its readiness there so the Backend's `/health` can speak for all three layers
    — which is what PRD Section 6's single-machine criterion asks of one endpoint.

    `backend_base_url` overrides the configured URL. Needed when `transport` is
    an `ASGITransport` aimed straight at the backend app: that app's own routes
    are prefix-free (`/health`), because the `/api/v1` prefix comes from the
    mount in `axis/asgi.py`. Requests through the transport bypass the mount, so
    they must not carry the prefix.
    """
    resolved = settings or get_settings()
    frontend_settings: FrontendSettings = for_frontend(resolved)

    # Readiness is determined here, not in a lifespan hook, for the same reason
    # the Backend wires itself synchronously: `httpx.ASGITransport` does not run
    # lifespan events, so a flag set there would be absent under test and present
    # in production. The Backend's /health reports this so one endpoint can speak
    # for all three layers, per PRD Section 6.
    ready = TEMPLATES_DIR.is_dir() and STATIC_DIR.is_dir()
    if shared_state is not None:
        shared_state.frontend_ready = ready  # type: ignore[attr-defined]
        if not ready:
            shared_state.frontend_error = (  # type: ignore[attr-defined]
                f"templates or static directory missing under {Path(__file__).parent}"
            )
    if not ready:
        logger.error("Frontend assets are missing; the UI will not render.")

    app = FastAPI(title="Axis")
    app.state.frontend_settings = frontend_settings
    app.state.backend = BackendClient(
        base_url=backend_base_url or frontend_settings.backend_base_url,
        transport=transport,
    )

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    # Exposed to every template as `asset('app.css')`. See `_asset_url`: this is what
    # makes "reload and the fix is there" reliable, which in a tool driven live in front
    # of a class is not a nicety.
    templates.env.globals["asset"] = _asset_url
    # A global rather than a key in each context. `_answer.html` is included from the
    # canvas, from Compare and from the pain-point result, and a control that renders
    # on two of those three is worse than one that renders nowhere — the reporter
    # learns it exists and then cannot find it.
    templates.env.globals["feedback_reasons"] = FEEDBACK_REASONS
    # `| md` in place of `| e` wherever model prose is shown. It escapes internally,
    # so it is not an opt-out of autoescaping — see `_inline_markdown`.
    templates.env.filters["md"] = _inline_markdown
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(
        request: Request, stage: str | None = None, document: str | None = None
    ) -> HTMLResponse:
        """The canvas, and a line to ask a question with.

        `?stage=` opens one card. It is how a page without JavaScript expands a stage —
        every collapsed card is a link here — and with the script running it is the URL
        `axis.js` mirrors into `/canvas` so a reload lands where the student was.

        Health is fetched server-side so the shell renders in one round trip and
        shows real status on first paint rather than flashing an empty state.
        """
        client: BackendClient = request.app.state.backend
        try:
            health = await client.health()
        except httpx.HTTPError as exc:
            # Degrade to a page that says what is wrong. A stack trace in the
            # browser during a live demo is the worst available outcome.
            logger.warning("Could not reach the backend for health: %s", exc)
            health = {
                "status": "error",
                "layers": [],
                "available_strategies": [],
                "config_error": f"The Frontend could not reach the Backend at "
                f"{frontend_settings.backend_base_url}.",
            }

        available = set(health.get("available_strategies") or [])
        documents = await _documents(client, request, corpus=_corpus(request))
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "health": health,
                # Both strategies, always listed. One may be `enabled: False` — an LLM
                # provider that cannot call tools leaves Agentic RAG unrunnable — and it
                # is shown disabled *with its reason* rather than hidden, because the
                # comparison is the product and a missing half needs explaining.
                "strategies": _strategy_rows(available),
                "limits": frontend_settings,
                "fonts_available": _vendored(_FONT_FILES),
                "documents": documents,
                "nav": "run",
                "session_id": request.cookies.get(_SESSION_COOKIE),
                **_session_keys(
                    await _session_state(client, request),
                    corpus=_corpus(request),
                    limit=frontend_settings.max_files_per_session,
                ),
                "demo_questions": await _demo_questions(client, documents, corpus=_corpus(request)),
                "pace_ms": _pace(request),
                "pace_choices": PACE_CHOICES,
                "web_search": _web_search(request),
                "cache_on": _cache_enabled(request),
                "flash": request.query_params.get("flash"),
                # **Answering only.** Indexing runs once per document and then stays
                # true for the whole session, so redrawing it above every question cost
                # half the board permanently and squeezed the six answering stages into
                # unreadable slivers. It has its own page now; the index band stays
                # here, because "read by Search" is the one thing the Run page still
                # needs from that phase.
                **await _canvas_context(
                    request,
                    stage_id=stage,
                    document_id=document,
                    documents=documents,
                    phases=("query",),
                ),
            },
        )

    # -- the other readings -----------------------------------------------
    #
    # Pages, not tabs. Both span more than the run on the canvas — Compare spans two
    # strategies and the trace spans every step of every run — so neither is a view *of*
    # the pipeline on screen. As radios beside it they made the canvas one option among
    # four; as links they cost a navigation the back button undoes.

    async def _chrome(request: Request) -> dict:
        """The top bar, the rail, the body, the footer — for every page but Run.

        **The rail renders everywhere now, so this has to be complete.** Jinja's
        `Undefined` *raises* on `>=`, on `in`, and on iteration, so a rail group whose
        data this forgot would not degrade to an empty group — it would 500 the page.
        Three keys are exactly that shape: `limits` (compared with `>=` for the upload
        limit), `pace_choices` (iterated), and `indexed_documents` (an `in` test). They
        are supplied here even where the group that reads them is not drawn, because
        "which groups this page draws" is a decision in the template and this should not
        have to know it.

        **Still no new round trips.** `documents` defaults empty rather than being
        fetched: the group that lists them renders on Run and Summarize, and both build
        their own context with the real list. Everything else is a cookie read or a
        settings read, and the corpus counts ride along on the `SessionInfo` fetch that
        was already happening for spend and turn count. The saving this docstring used
        to bank — two round trips per load of Compare and the raw trace — is intact.

        Two entries look like the rail's and are not. `strategies` is what the top bar
        counts in its "2 / 2" readout, and `selected_strategy` is `body[data-strategy]`,
        which is where every strategy-coloured element on these pages — the trace page's
        chips, the comparison's columns — resolves `--strategy` from.
        """
        client: BackendClient = request.app.state.backend
        health = await _health_or_degraded(client)
        available = set(health.get("available_strategies") or [])
        return {
            "health": health,
            "strategies": _strategy_rows(available),
            "fonts_available": _vendored(_FONT_FILES),
            "selected_strategy": _default_strategy(available),
            "session_id": request.cookies.get(_SESSION_COOKIE),
            **_session_keys(
                await _session_state(client, request),
                corpus=_corpus(request),
                limit=frontend_settings.max_files_per_session,
            ),
            # The rail's own data. Defaults that render a correct, empty group rather
            # than an exception — see above.
            "limits": frontend_settings,
            "documents": [],
            "indexed_documents": [],
            "selected_document": None,
            "pace_ms": _pace(request),
            "pace_choices": PACE_CHOICES,
            "web_search": _web_search(request),
            "cache_on": _cache_enabled(request),
            "flash": None,
        }

    @app.get("/compare", response_class=HTMLResponse)
    async def compare_page(request: Request) -> HTMLResponse:
        """Two runs, side by side, chosen rather than assumed.

        One query parameter per strategy — `?naive_rag=…&agentic_rag=…` — read straight
        off the query string rather than declared, so adding a strategy adds a column
        and needs nothing here. The names are the strategy values, which is what makes
        the form in `_runpicker.html` a plain `GET` with no mapping in between.
        """
        chrome = await _chrome(request)
        available = set(chrome["health"].get("available_strategies") or [])
        chosen = {
            s.value: request.query_params[s.value]
            for s in DEMO_STRATEGIES
            if request.query_params.get(s.value)
        }
        return templates.TemplateResponse(
            request=request,
            name="compare.html",
            context={
                **chrome,
                "nav": "compare",
                "comparison": _comparison(
                    request.cookies.get(_SESSION_COOKIE), available, chosen
                ),
            },
        )

    @app.get("/indexing", response_class=HTMLResponse)
    async def indexing_page(
        request: Request, stage: str | None = None, document: str | None = None
    ) -> HTMLResponse:
        """The four stages that turn a file into something searchable.

        **Its own page, because it runs on a different clock.** Indexing happens once
        per document and then stays true for the rest of the session; answering happens
        per question. Drawing both above every question spent half the board on a phase
        that had not changed since the upload, and left the six answering stages sharing
        the other half — at which point their names clipped to "Re…", "Ro…", "De…" and
        the diagram stopped naming its own stages.

        The index band stays on the Run page as well. It is the object both phases
        touch, and "written by Store, read by Search" is the sentence that makes the
        answering track's Search stage mean something without this page open beside it.

        `?document=` picks which document the four stages describe, the same way it did
        when this track lived on the Run page; `?stage=` opens one card, and index cards
        now link back here rather than to `/`.
        """
        client: BackendClient = request.app.state.backend
        documents = await _documents(client, request, corpus=_corpus(request))
        return templates.TemplateResponse(
            request=request,
            name="indexing.html",
            context={
                **await _chrome(request),
                "nav": "indexing",
                "documents": documents,
                **await _canvas_context(
                    request,
                    stage_id=stage,
                    document_id=document,
                    documents=documents,
                    phases=("index",),
                    card_base="/indexing",
                ),
            },
        )

    @app.get("/trace", response_class=HTMLResponse)
    async def trace_page(request: Request, id: str | None = None) -> HTMLResponse:
        """Every step of one run, exactly as recorded, beside a list of the others.

        Scoped to a single `trace_id` rather than the whole session, because the session
        holds every upload's indexing steps and every earlier question, and reading them
        as one undivided list tells you nothing about which run did what. `?id=` chooses;
        the most recent is the default, because the run someone just watched is the one
        they came to check.

        An unknown id falls back to that default rather than erroring. The only ways to
        hold one are a stale link and a bookmark taken before a reset, and in both cases
        the newest run is what the reader wants — a 404 would be technically correct and
        useless.
        """
        client: BackendClient = request.app.state.backend
        session_id = request.cookies.get(_SESSION_COOKIE)
        token = request.cookies.get(_TOKEN_COOKIE)

        steps: list[dict] = []
        if session_id and token:
            try:
                steps = await client.trace_steps(session_id, token=token)
            except httpx.HTTPError as exc:
                logger.warning("Could not read the trace: %s", exc)

        traces = _traces(steps)
        known = {t["id"] for t in traces}
        selected = id if id in known else (traces[0]["id"] if traces else None)

        return templates.TemplateResponse(
            request=request,
            name="trace.html",
            context={
                **await _chrome(request),
                "nav": "trace",
                "traces": traces,
                "selected_trace": selected,
                "trace": [s for s in steps if s.get("trace_id") == selected],
            },
        )

    async def _demo_questions(
        client: BackendClient, documents: list[dict], *, corpus: str
    ) -> list[dict]:
        """The labelled example questions — but only when their corpus is the live one.

        **A prediction is a claim about specific documents.** "Splitting this question
        finds a document the blended search misses" is true of the demo corpus and of
        nothing else, so offering these beside somebody's own unrelated PDFs would have
        the platform confidently predicting outcomes the harness never measured.

        Two conditions, and the first is new. The demo corpus has to be the one that is
        *active*, because a question whose predicted outcome was measured against
        documents the current index does not search is a prediction about nothing. And
        the set has to be complete: the Backend sends the filenames it was measured
        against, checked here against what that corpus holds.

        The filename check was once the whole gate, which was adequate and not correct
        — nothing stops a student uploading a file called `acme-msa-2026.md`. Now the
        `documents` list is already narrowed to one corpus by identity, so a coincidence
        of names cannot satisfy it.

        In practice they are absent whenever the demo corpus is turned off, which is the
        default — and reappear on their own once an instructor enables it, loads the set
        and has it selected.

        Degraded to an empty list rather than allowed to fail the render. The questions
        are a teaching scaffold; a page that draws the canvas, the ask box and the
        trace but not four example sentences is a mildly worse page, whereas a 500 in
        front of a class is the worst available outcome — the same reasoning the health
        fetch above already follows.
        """
        if corpus != DEMO_CORPUS:
            return []
        try:
            demo = await client.demo_questions()
        except httpx.HTTPError as exc:
            logger.warning("Could not fetch the demo question set: %s", exc)
            return []

        indexed = {d.get("filename") for d in documents}
        required = set(demo.get("documents") or [])
        if not required or not required.issubset(indexed):
            return []
        return demo.get("questions") or []

    # -- session ----------------------------------------------------------

    async def _session_is_live(request: Request, session_id: str, token: str) -> bool:
        """Whether the session this cookie names still exists.

        **A cookie is a claim, not a session.** It outlives the store it refers to in
        two ordinary ways: the process restarted, or — on the hosted deployment, where
        the store is `:memory:` — the instance that held it was recycled and the next
        request landed on a fresh one. The browser keeps presenting the old id either
        way, and it is a perfectly well-formed id for a session that is gone.

        Trusting it produced an `Internal Server Error` on the deployment. Every route
        passed the id straight through, the Backend answered `401 Unauthorized` because
        no such session exists, and `raise_for_status()` turned that into a 500 — so a
        student who left a tab open came back to a stack trace and no way out of it but
        clearing cookies, which is not something to ask of a class.

        One in-process call, not a network hop: the Frontend reaches the Backend over
        `httpx.ASGITransport` (`axis/asgi.py`), so this is a function call wearing HTTP
        semantics.

        Only `401` and `404` mean *gone*. Any other failure is treated as transient and
        the session is kept — minting a new one because the Backend hiccuped would
        abandon a student's uploads over a blip.
        """
        try:
            await request.app.state.backend.get_session(session_id, token=token)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 404):
                logger.info(
                    "Session %s is no longer known; starting a fresh one.", session_id
                )
                return False
            return True
        except httpx.HTTPError:
            return True
        return True

    async def _session(request: Request) -> tuple[str, str, dict[str, str]]:
        """The caller's session, created on first use — or on first use after it went.

        Held in a cookie rather than in server memory so a page reload keeps the
        same workspace and its uploaded documents. `httponly` because no script
        needs to read it, and the token is the only thing standing between one
        student's documents and another's (System Design Section 6.4).

        The cookie is **checked** rather than taken at face value; see
        `_session_is_live` for what a stale one used to do.
        """
        session_id = request.cookies.get(_SESSION_COOKIE)
        token = request.cookies.get(_TOKEN_COOKIE)
        if session_id and token and await _session_is_live(request, session_id, token):
            return session_id, token, {}

        created = await request.app.state.backend.create_session()
        # Returned rather than set here, because the caller may be rendering a
        # template rather than redirecting — and a cookie set on a throwaway
        # Response object is a cookie the browser never sees, which would mint a
        # fresh session on every question and silently lose the uploads.
        return (
            created["session_id"],
            created["token"],
            {_SESSION_COOKIE: created["session_id"], _TOKEN_COOKIE: created["token"]},
        )

    def _persist(response: Response, cookies: dict[str, str]) -> None:
        for name, value in cookies.items():
            response.set_cookie(
                name,
                value,
                httponly=True,
                samesite="lax",
                max_age=resolved.server.session_token_ttl_seconds,
            )

    async def _session_state(client: BackendClient, request: Request) -> dict:
        """Spend and turn count, from the one call that has both.

        `spend` is `None` when there is no session yet, so the readout is omitted
        rather than showing a misleading $0.0000 for a session that does not exist.
        Watching that number move is part of what the platform teaches about agentic
        cost, so it belongs in the chrome rather than behind a click.

        `turns` comes from the same response deliberately. The sidebar shows how many
        exchanges a follow-up can refer back to, and the Backend is the only thing
        that knows — the conversation is a watermark over the runs, so counting runs
        here would be right until somebody pressed "New conversation". One fetch, one
        source, and the count cannot disagree with the history the rewriter is
        actually handed.

        `corpora` rides along for the same reason: the rail draws its corpus group on
        every page, and counting documents per corpus in the Frontend would mean a
        second round trip on every render for a number this response already carries.
        """
        empty = {"spend": None, "turns": 0, "corpora": {}}
        session_id = request.cookies.get(_SESSION_COOKIE)
        token = request.cookies.get(_TOKEN_COOKIE)
        if not (session_id and token):
            return empty
        try:
            info = await client.get_session(session_id, token=token)
            return {
                "spend": float(info["spent_usd"]),
                "turns": int(info.get("turn_count") or 0),
                "corpora": dict(info.get("corpora") or {}),
            }
        except (httpx.HTTPError, KeyError, ValueError):
            return empty

    async def _documents(
        client: BackendClient, request: Request, *, corpus: str | None = None
    ) -> list[dict]:
        """This session's documents. Named a corpus, only that one's.

        Every caller that feeds a document list to a page passes the active corpus,
        because a list showing files the active index cannot reach is a list of things
        that will not be found — the exact confusion the toggle exists to remove.
        """
        session_id = request.cookies.get(_SESSION_COOKIE)
        token = request.cookies.get(_TOKEN_COOKIE)
        if not (session_id and token):
            return []
        try:
            return await client.documents(session_id, token=token, corpus=corpus)
        except httpx.HTTPError:
            # A stale cookie from a previous run, most likely. An empty list is
            # the honest answer and the next action will mint a new session.
            return []

    # -- upload -----------------------------------------------------------

    @app.post("/upload", response_class=HTMLResponse)
    async def upload(request: Request, files: list[UploadFile] = File(...)) -> Response:
        client: BackendClient = request.app.state.backend
        response = RedirectResponse("/", status_code=303)
        session_id, token, cookies = await _session(request)
        _persist(response, cookies)

        payload = [
            ("files", (f.filename or "unnamed", await f.read(), f.content_type or ""))
            for f in files
        ]
        result = await client.upload(
            session_id,
            token=token,
            files=payload,
            pace_ms=_pace(request),
            # The corpus the student is looking at, not `mine` unconditionally — an
            # upload made while the demo corpus is active belongs to the demo corpus,
            # and putting it elsewhere would index files into a scope the page they
            # are on does not search.
            corpus=_corpus(request),
        )

        # Redirect rather than render, so a browser refresh does not re-upload.
        # The per-file outcome is summarised in the flash; the document list on the
        # page carries the detail.
        if result.status_code == 200:
            body = result.json()
            note = f"{body['accepted']} indexed"
            if body["rejected"]:
                note += f", {body['rejected']} failed"
            note = "; ".join([note, *_upload_findings(body.get("documents") or [])])
        else:
            note = result.json().get("message", "Upload failed.")
        response.headers["location"] = f"/?flash={quote(note)}"
        return response

    @app.post("/demo-documents", response_class=HTMLResponse)
    async def load_demo_documents(request: Request) -> Response:
        """Index the corpus the labelled questions were measured against.

        A plain form post with a redirect, exactly like `/upload` — so it works with
        JavaScript disabled, which PRD Section 6 requires of the labelled question
        set it exists to make runnable.
        """
        client: BackendClient = request.app.state.backend
        response = RedirectResponse("/", status_code=303)

        # Refused before a session is minted, let alone a document indexed. The
        # sidebar omits the button when this is off, but a stale page, a bookmark or a
        # second tab all reach the route without it — and this is the half that spends
        # money.
        if not frontend_settings.demo_documents_enabled:
            response.headers["location"] = "/?flash=" + quote(
                "The demo corpus is turned off. Set AXIS_DEMO__DOCUMENTS_ENABLED=true "
                "to offer it."
            )
            return response

        session_id, token, cookies = await _session(request)
        _persist(response, cookies)

        # **The set lands in the `demo` corpus, so the browser is switched to it.**
        # It has to be: the route takes no corpus and never has, because the labelled
        # questions are claims about these five files and have to be reachable as a set
        # whatever a student has uploaded. Indexing them while the page keeps looking at
        # `mine` would spend five embedding round trips and change nothing on screen,
        # which is the worst available outcome for the one button that costs money.
        response.set_cookie(
            _CORPUS_COOKIE,
            DEMO_CORPUS,
            samesite="lax",
            max_age=resolved.server.session_token_ttl_seconds,
        )

        result = await client.load_demo_documents(
            session_id, token=token, pace_ms=_pace(request)
        )
        if result.status_code == 200:
            body = result.json()
            note = f"demo set: {body['accepted']} indexed"
            if body["rejected"]:
                note += f", {body['rejected']} failed"
            note = "; ".join([note, *_upload_findings(body.get("documents") or [])])
        else:
            note = result.json().get("message", "Could not load the demo documents.")
        response.headers["location"] = f"/?flash={quote(note)}"
        return response

    # -- summarize --------------------------------------------------------
    #
    # A page of its own beside Run, Compare and Trace, rather than a button in the rail
    # that ran the whole corpus on one click.
    #
    # Two reasons, and the second is the teaching one. Practically: the run is the most
    # expensive action Axis offers and it had no confirmation and no choice — a click in
    # a sidebar read every document a student had uploaded. And the page it produced was
    # not reachable except by pressing that button again, so a student who looked at the
    # trace to see the map-reduce steps lost the summary they went to explain.
    #
    # Pedagogically: summarizing is the *contrast* that justifies retrieval — read
    # everything, or read the relevant part — so it belongs next to Run in the nav, at
    # the same level, not filed under setup. Choosing documents makes the cost curve
    # something a class can watch: summarize one document, then four, and the price moves
    # with the corpus in a way asking a question never does.

    async def _summarize_context(
        request: Request, *, summary: dict | None, selected: set[str] | None
    ) -> dict:
        """The Summarize page: the document picker, and a summary if one has run.

        `selected` is what the checkboxes should show — the ids that produced the
        summary on screen, so what is displayed is always attributable to a selection.
        `None` means "no run yet", and everything ready is pre-checked, which is both
        the useful default and the behaviour the rail's button used to have.
        """
        client: BackendClient = request.app.state.backend
        # The active corpus only. Summarizing is meant to scale with the corpus, so a
        # picker offering both would let a student check a box in one and read a cost
        # curve for a set of documents they are not looking at.
        documents = await _documents(client, request, corpus=_corpus(request))
        return {
            **await _chrome(request),
            "nav": "summarize",
            "documents": documents,
            # `document_id` rather than `id` — the Backend's `DocumentStatus` names it
            # that, and it is `None` for a file that never got as far as being indexed.
            "selected_documents": (
                selected
                if selected is not None
                else {
                    d["document_id"]
                    for d in documents
                    if d.get("status") == "ready" and d.get("document_id")
                }
            ),
            "summary": summary,
        }

    # -- why agentic ------------------------------------------------------
    #
    # The page the platform was missing. Axis could always show what orchestration
    # *costs*; it could never show the shape of the problem orchestration solves, so
    # a student learned a price without learning what they were buying.
    #
    # Four pain points, four *different* mechanisms, and that is the lesson rather
    # than a detail — a student who leaves believing "agentic is better" has learned
    # less than one who leaves knowing which failure calls for which fix.

    async def _pain_point_context(
        request: Request,
        *,
        results: dict | None = None,
        flash: str | None = None,
        selected: str | None = None,
    ) -> dict:
        client: BackendClient = request.app.state.backend
        active = _corpus(request)
        documents = await _documents(client, request, corpus=active)
        indexed = {d["filename"] for d in documents if d.get("status") == "ready"}

        try:
            offered = await client.pain_points()
        except httpx.HTTPError as exc:
            # Degraded rather than fatal, like the labelled questions: a page that
            # cannot list four demonstrations is worse than one that can, and much
            # better than a 500 in front of a class.
            logger.warning("Could not read the pain-point set: %s", exc)
            offered = {"pain_points": [], "documents": []}

        # **The page has two modes, and the difference is stated rather than implied.**
        #
        # The symptom and the mechanism are facts about retrieval, not about ACME, so
        # they hold whatever is indexed. What cannot survive a corpus switch is the
        # *measurement*: every `measured` sentence is the harness's figure for a
        # specific golden question against these specific documents, and there is no
        # golden answer for a question a student typed thirty seconds ago.
        #
        # So: with the demo corpus live and complete, the card runs its own question
        # and carries its number. Otherwise the student supplies the question and the
        # card says plainly that nothing measured this one. Every claim is verified or
        # is visibly marked as not verified, and there is no third state — that rule
        # is what the whole page rests on.
        wanted = set(offered.get("documents") or [])
        verified = active == DEMO_CORPUS and bool(wanted) and wanted <= indexed

        points = offered.get("pain_points") or []
        held = results or {}
        return {
            **await _chrome(request),
            "nav": "why",
            "pain_points": points,
            # Which of the four the detail below the row is describing.
            "selected_point": _selected_point(points, selected, held),
            # The filenames the measurements were taken against — for the banner that
            # explains how to get back into verified mode. Not `corpus`, which the rail
            # uses for the *name* of the active one; two different things, and one
            # shadowing the other in this context dict is how the rail would lose its
            # toggle on exactly the page that most needs it.
            "demo_documents": sorted(wanted),
            "verified": verified,
            # Whether a run is possible at all. Unverified mode still needs something
            # indexed: two strategies retrieving from an empty index demonstrate
            # nothing except that the index is empty.
            "runnable": verified or bool(indexed),
            "results": held,
            "flash": flash,
            # The stage names, which the result fragment renders as chips. Normally
            # these arrive with the canvas context; this page has no canvas, so it
            # has to pass them itself — and it uses the *same* mapping rather than a
            # local copy, because two lists of stage names would drift and a student
            # would see one word here and another on the Run page.
            "STAGE_TITLES": STAGE_TITLES,
        }

    @app.get("/why-agentic", response_class=HTMLResponse)
    async def why_agentic(request: Request, point: str | None = None) -> HTMLResponse:
        """The four failures on screen at once, and one of them open below.

        `?point=` chooses which. It is the same shape as `?stage=` on the canvas and
        `?id=` on the Trace page — a plain link per card, resolved on the server, so a
        browser with no JavaScript selects by navigating and a reload lands where the
        student was. See `_selected_point` for how an absent or stale value resolves.

        Results are held rather than recomputed, like the summary: a navigation
        should not charge for four more runs, and a student who ran a demonstration
        and went to read its trace needs it still on the page when they come back.
        """
        session_id = request.cookies.get(_SESSION_COOKIE)
        return templates.TemplateResponse(
            request=request,
            name="why.html",
            context=await _pain_point_context(
                request,
                results=_PAINPOINTS.get(session_id or ""),
                selected=point,
                # Read rather than dropped, which it was until now. `POST /corpus/clear`
                # redirects back to the referring page with `?flash=`, and this page
                # silently ignored it — so clearing a corpus from here confirmed
                # nothing, while also discarding the held result the detail was showing.
                flash=request.query_params.get("flash"),
            ),
        )

    async def _refuse(request: Request, point_id: str, why: str) -> HTMLResponse:
        """Re-render the page with a reason, on the card the student was working on.

        **The selection has to be passed explicitly here.** These are the paths where a
        run was declined without spending anything, and the default selection is "the
        card that has a result" — which is either some *other* card the student ran
        earlier, or the first one. Either way the message would land beside a card it is
        not about, which reads as the page having gone wrong rather than as a request to
        fill the box in front of you.
        """
        return templates.TemplateResponse(
            request=request,
            name="why.html",
            context=await _pain_point_context(
                request,
                results=_PAINPOINTS.get(request.cookies.get(_SESSION_COOKIE) or ""),
                selected=point_id,
                flash=why,
            ),
        )

    @app.post("/why-agentic/{point_id}", response_class=HTMLResponse)
    async def run_pain_point(
        request: Request,
        point_id: str,
        question: str = Form(""),
        context_question: str = Form(""),
    ) -> HTMLResponse:
        """Run one pain point through both strategies and show them side by side.

        **Both strategies, one question, in that order** — baseline first, so the
        page reads as "here is what happens, and here is what the extra machinery
        changes" rather than as a victory lap.

        The memory demonstration is the one that runs *two* queries per strategy,
        because a follow-up needs a turn in front of it to mean anything. The context
        question is asked first and its answer discarded; what the page shows is the
        follow-up, which is the only turn where the two strategies differ.

        **The question is the card's own, or the student's, and never a blend.** With
        the demo corpus live the form carries no question field and the golden one is
        used, so the card's measured figure describes the run on screen. Against any
        other corpus the student supplies it — the shape of the failure is still
        demonstrated, the number is not claimed, and the card says so.

        An empty submission in that mode is refused *here*, before the Backend is
        called at all — the same rule `/summarize` follows for an empty selection, and
        for the same reason: it costs nothing, not even a round trip.

        A plain form post rendering its own page, so it works with JavaScript
        disabled — the same shape as `/summarize`.
        """
        client: BackendClient = request.app.state.backend
        offered = (await client.pain_points()).get("pain_points") or []
        point = next((p for p in offered if p["id"] == point_id), None)
        if point is None:
            return await why_agentic(request)

        # Read once, for both strategies and both turns. Two strategies reading
        # different corpora is not a comparison of strategies, and the memory
        # demonstration's context turn has to land in the same place its follow-up
        # will look.
        corpus = _corpus(request)
        verified = corpus == DEMO_CORPUS

        # The card's own question in verified mode, whatever the form carried
        # otherwise. Not `submitted or point["question"]`: falling back to the golden
        # question when a student left the box empty would run a question about ACME
        # against their documents and print a measured figure beside the result.
        asked = point["question"] if verified else question.strip()
        context = (
            point.get("context_question") if verified else context_question.strip()
        )
        if not asked:
            return await _refuse(
                request, point_id, "Type a question for this demonstration to run."
            )
        if point.get("context_question") and not context:
            # The memory card is two turns by construction. One turn cannot show a
            # follow-up failing to resolve a reference, because there is nothing for
            # the reference to point at — so a half-filled form is refused rather than
            # run into a demonstration that would show nothing either way.
            return await _refuse(
                request,
                point_id,
                "This one needs both turns: a first question, then a follow-up that "
                "refers back to it.",
            )

        session_id, token, cookies = await _session(request)
        runs: dict[str, dict] = {}

        for strategy in (Strategy.NAIVE_RAG.value, Strategy.AGENTIC_RAG.value):
            # The context turn first, for the memory demonstration only. Its answer
            # is not shown: it is scaffolding, and showing it would put the same
            # exchange on the page twice.
            if context:
                await client.query(
                    session_id,
                    token=token,
                    question=context,
                    strategy=strategy,
                    pace_ms=0,
                    web_search=_web_search(request),
                    cache=_cache_enabled(request),
                    corpus=corpus,
                )

            response = await client.query(
                session_id,
                token=token,
                question=asked,
                strategy=strategy,
                pace_ms=0,
                web_search=_web_search(request),
                cache=_cache_enabled(request),
                corpus=corpus,
            )
            if response.status_code != 200:
                body = response.json()
                runs[strategy] = {"error": body.get("message", "The query failed.")}
                continue

            answer = response.json()
            trace = await client.trace_steps(
                session_id, token=token, trace_id=answer["trace_id"]
            )
            _record_run(
                session_id,
                strategy=strategy,
                question=asked,
                answer=answer,
                trace=trace,
            )
            runs[strategy] = {
                "answer": answer,
                # What each path actually did, counted from its own trace rather
                # than asserted. The whole page rests on these being real.
                "steps": len(trace),
                "retrievals": sum(
                    1 for s in trace if s.get("step_type") == "retrieve"
                ),
                "stages": sorted(
                    {
                        str(s.get("step_type"))
                        for s in trace
                        if str(s.get("step_type")) in _RUN_STAGES
                    }
                ),
                # Whether the mechanism this card is *about* actually did anything.
                # See `_mechanism_fired` — this is the difference between the page
                # teaching and the page misleading.
                "fired": _mechanism_fired(point_id, trace),
            }

        # `question` and `verified` travel with the result, because the fragment has to
        # say *what* was asked and whether the card's number describes it. Held rather
        # than re-derived on the next render: the cookie can change between the run and
        # the reload, and a result relabelled "verified" by a corpus switch would be the
        # exact dishonesty this page is built to avoid.
        held = {
            "point_id": point_id,
            "runs": runs,
            "question": asked,
            "context_question": context or None,
            "verified": verified,
        }
        _remember_pain_point(session_id, held)
        rendered = templates.TemplateResponse(
            request=request,
            name="why.html",
            # No `selected` needed: `held` names the point that just ran, and
            # `_selected_point` prefers it over the default for exactly this case.
            context=await _pain_point_context(request, results=held),
        )
        _persist(rendered, cookies)
        return rendered

    @app.get("/summarize", response_class=HTMLResponse)
    async def summarize_page(request: Request) -> HTMLResponse:
        """The picker, and the last summary this session produced.

        The last summary is held rather than recomputed. Re-running it on a page load
        would charge for a navigation, and this is the one action expensive enough that
        the difference shows up in the session's spend readout.
        """
        session_id = request.cookies.get(_SESSION_COOKIE)
        held = _SUMMARIES.get(session_id or "")
        return templates.TemplateResponse(
            request=request,
            name="summary.html",
            context=await _summarize_context(
                request,
                summary=held["summary"] if held else None,
                selected=held["selected"] if held else None,
            ),
        )

    @app.post("/summarize", response_class=HTMLResponse)
    async def summarize(
        request: Request, documents: list[str] | None = Form(None)
    ) -> HTMLResponse:
        """Summarize the chosen documents.

        Renders its own page rather than redirecting, because the summary *is* the
        result — a redirect would show it once and lose it on the next reload, and
        unlike an upload there is no re-submission hazard to avoid.

        **An empty selection is refused here, before the Backend is called at all.** A
        POST carrying no `documents` field is either every box unchecked or a stale page
        submitting, and neither is a request to read the whole corpus. Caught in the
        Frontend so it costs nothing — not even a round trip — with the same rule
        restated in `ai_backend/summarize.py`, which is where it has to hold for any
        caller.

        A plain form post, so it works with JavaScript disabled.
        """
        client: BackendClient = request.app.state.backend
        session_id, token, cookies = await _session(request)
        chosen = documents or []

        summary: dict | None = None
        flash: str | None = None
        if not chosen:
            flash = "Select at least one document to summarize."
        else:
            result = await client.summarize(
                session_id, token=token, document_ids=chosen, corpus=_corpus(request)
            )
            if result.status_code == 200:
                summary = result.json()
                _hold_summary(session_id, summary=summary, selected=set(chosen))
            else:
                # A cap, or an invalid configuration. Both say which.
                flash = result.json().get("message", "The summary failed.")

        rendered = templates.TemplateResponse(
            request=request,
            name="summary.html",
            context={
                **await _summarize_context(
                    request, summary=summary, selected=set(chosen)
                ),
                "flash": flash,
            },
        )
        _persist(rendered, cookies)
        return rendered

    # -- ask --------------------------------------------------------------

    async def _run_query(
        request: Request, *, question: str, strategy: str, document_id: str | None = None
    ) -> tuple[dict, dict[str, str]]:
        """Ask one question and assemble everything a render needs.

        Shared by `/ask` and `/ask/fragment` so the two cannot drift — the fragment
        exists to be swapped in place of the full page's result section, and if it
        computed its context differently the two paths would disagree about
        groundedness or cost while looking identical.

        `document_id` carries the indexing track's selection through the ask. It arrives
        as a hidden field on the form, which is what keeps the scripts-disabled path
        honest: with JavaScript the canvas is re-fetched with the parameter still in the
        address bar, and without it the whole page re-renders, so the selection has to
        be *submitted* or asking a question would silently move the track back to the
        last document uploaded.

        Returns the template context and any cookies the caller must persist.
        """
        client: BackendClient = request.app.state.backend
        health = await _health_or_degraded(client)
        session_id, token, cookies = await _session(request)
        corpus = _corpus(request)

        result = await client.query(
            session_id,
            token=token,
            question=question,
            strategy=strategy,
            pace_ms=_pace(request),
            web_search=_web_search(request),
            cache=_cache_enabled(request),
            corpus=corpus,
        )

        answer: dict | None = None
        flash: str | None = None
        trace: list[dict] = []
        if result.status_code == 200:
            answer = result.json()
            trace = await client.trace_steps(
                session_id, token=token, trace_id=answer["trace_id"]
            )
            _record_run(
                session_id,
                strategy=strategy,
                question=question,
                answer=answer,
                trace=trace,
            )
        else:
            body = result.json()
            # A cap, an unavailable strategy, and a provider fault are three
            # different things, and the message says which (backend/core/errors.py).
            flash = body.get("message", "The query failed.")

        available = set(health.get("available_strategies") or [])
        documents = await client.documents(session_id, token=token, corpus=corpus)
        context = {
            "health": health,
            "strategies": _strategy_rows(available),
            "limits": frontend_settings,
            "fonts_available": _vendored(_FONT_FILES),
            "documents": documents,
            "nav": "run",
            "trace": trace,
            "question": question,
            "session_id": session_id,
            **_session_keys(
                await _session_state(client, request),
                corpus=_corpus(request),
                limit=frontend_settings.max_files_per_session,
            ),
            "demo_questions": await _demo_questions(client, documents, corpus=_corpus(request)),
            "pace_ms": _pace(request),
            "pace_choices": PACE_CHOICES,
            "web_search": _web_search(request),
            "cache_on": _cache_enabled(request),
            "flash": flash,
            # Last, so `selected_strategy` is the one that just ran rather than the
            # default — the canvas's shape depends on it, and an agentic run rendered
            # against the naive tracks would be missing two of its own cards.
            #
            # **No `expand="synthesize"` any more.** The server used to open the
            # Generate card after a run, because the answer was only readable inside
            # it. The answer is now rendered above the pipeline by `index.html`, so
            # expanding that card would show the same text twice — and on a
            # single-track board the expanded row is tall enough to push every other
            # stage out of the track's scroll, which is how the answer came to look
            # clipped and missing.
            **await _canvas_context(
                request,
                strategy=strategy,
                document_id=document_id,
                documents=documents,
                # index.html, so the same single track the Run page draws.
                phases=("query",),
            ),
        }
        return context, cookies

    def _asked(question: str, preset: str | None) -> str:
        """Which text the student actually submitted.

        A labelled example question arrives as `preset`, from a submit button in the
        same form as the textarea (see index.html). `preset` wins when present: the
        student pressed a specific question, and whatever was left in the box is not
        what they asked for.

        `question` is therefore optional at the route, and validated here rather than
        by `Form(...)` — a blank submission with no preset is a student pressing Ask
        on an empty box, which deserves a message rather than a 422.
        """
        chosen = (preset or question or "").strip()
        return chosen

    @app.post("/ask", response_class=HTMLResponse)
    async def ask(
        request: Request,
        question: str = Form(""),
        strategy: str = Form(...),
        preset: str | None = Form(None),
        document: str | None = Form(None),
    ) -> HTMLResponse:
        """Ask one question and render the answer beside its trace.

        The no-JavaScript path, and the one the form posts to natively. Both answer
        and trace are on one response on purpose: the answer is only half the point.
        A student who sees "16 weeks" without the retrieve and synthesize steps that
        produced it has learned an answer, not a system.
        """
        asked = _asked(question, preset)
        if not asked:
            return await index(request, document=document)

        context, cookies = await _run_query(
            request, question=asked, strategy=strategy, document_id=document
        )
        rendered = templates.TemplateResponse(
            request=request, name="index.html", context=context
        )
        _persist(rendered, cookies)
        return rendered

    @app.post("/ask/fragment", response_class=HTMLResponse)
    async def ask_fragment(
        request: Request,
        question: str = Form(""),
        strategy: str = Form(...),
        preset: str | None = Form(None),
        document: str | None = Form(None),
    ) -> HTMLResponse:
        """The same run, rendered as just the canvas.

        What axis.js swaps in, so a completed run does not reload the page and throw
        away the diagram the student was watching fill.

        Returns the *same* `_canvas.html` the full page includes rather than JSON for
        the client to render. Rendering an answer in JavaScript would mean two
        renderers that must agree about citations, groundedness and cost formatting
        for as long as the project lives.
        """
        context, cookies = await _run_query(
            request,
            question=_asked(question, preset),
            strategy=strategy,
            document_id=document,
        )
        rendered = templates.TemplateResponse(
            request=request, name="_canvas.html", context=context
        )
        # A failed query has no answer to render, so the reason has to travel in a
        # header — the fragment body would otherwise be an empty answer panel with
        # no explanation, which reads as a bug rather than a refusal.
        if context["flash"]:
            rendered.headers["X-Axis-Flash"] = quote(str(context["flash"]))
        _persist(rendered, cookies)
        return rendered

    @app.post("/reset", response_class=HTMLResponse)
    async def reset(request: Request) -> Response:
        """Start over: a clean session, an empty canvas.

        **What makes the demo repeatable.** Indexing is the first thing a class
        watches and it could only be watched once — the file limit refuses a second
        upload of the same document, and nothing cleared one. Running the demo for a
        second group meant clearing cookies in front of the room.

        Minting a fresh session is what does the work, rather than a cascade of
        deletes: documents, spend, run history and trace are all scoped to the session
        id, so a new one clears every one of them at once and there is no half-reset
        state to get wrong. The `DELETE` is only to free the vectors, which nothing
        else would ever reclaim.
        """
        client: BackendClient = request.app.state.backend
        session_id = request.cookies.get(_SESSION_COOKIE)
        token = request.cookies.get(_TOKEN_COOKIE)

        if session_id and token:
            await client.delete_session(session_id, token=token)
            # Presentation state the Frontend holds for the comparison, the answer pane
            # and the Summarize page. Keyed by session, so a new id would orphan rather
            # than reuse them — dropping them keeps the bounded dicts from filling with
            # dead sessions across a workshop. "Start over" also has to mean the summary
            # is gone: it describes documents that no longer exist.
            _RUNS.pop(session_id, None)
            _SUMMARIES.pop(session_id, None)

        response = RedirectResponse("/", status_code=303)
        # Deleted rather than overwritten: the next request has no session, so
        # `_session` mints one. Overwriting with a blank value would leave a cookie
        # the Backend then rejects, which reads as a broken session rather than none.
        for name in (_SESSION_COOKIE, _TOKEN_COOKIE):
            response.delete_cookie(name)
        return response

    @app.post("/session")
    async def ensure_session(request: Request) -> Response:
        """Mint a session now, if there is not one already.

        **Why this exists at all.** A session is created by whichever request first
        needs one — and for a new visitor that is the upload itself, whose cookies
        arrive with its *response*, after indexing has finished. So every poll during
        the first document's run went out with no session, got the honest empty answer,
        and the canvas a student was watching stayed blank for the one run they most
        needed to see. Every later run worked, which is exactly the shape of bug that
        survives testing.

        Called by `axis.js` before it starts watching. The no-JavaScript path does not
        need it: it never polls, and the server renders the finished run.
        """
        response = Response(status_code=204)
        _, _, cookies = await _session(request)
        _persist(response, cookies)
        return response

    def _back_here(request: Request) -> str:
        """Where a rail control returns to, safely, keeping which card was open.

        `Referer` is a header and therefore the caller's to set, so only a path on this
        site is ever reflected — reflecting it whole would make every one of these an
        open redirect, which is a real one however small the feature.

        **The `point` parameter is carried across, and only that one.** Four of the rail's
        controls render on the Why-agentic page — corpus, web search, cache, new
        conversation — and dropping the query string sent a student back to the first
        card every time they touched one. Switching corpus is the main thing you *do* on
        that page (the banner tells you to), so losing your place on it was the common
        case. An allow-list rather than passing the query through, because reflecting
        arbitrary parameters back out of a redirect is how the referer problem above
        starts again.
        """
        referer = urlparse(request.headers.get("referer") or "")
        path = referer.path or "/"
        if not path.startswith("/") or path.startswith("//"):
            return "/"
        point = parse_qs(referer.query).get("point", [""])[0]
        # Shape, not membership. The Frontend reaches the pain-point set over HTTP, so
        # checking a real id here would cost a round trip on every rail click — and it
        # would buy nothing: `_selected_point` already whitelists against the offered
        # ids, so an unknown-but-well-formed value falls back to a real card. What this
        # has to guarantee is only that nothing but a slug is ever reflected back into a
        # URL, which the pattern does.
        if path == "/why-agentic" and _POINT_ID.fullmatch(point):
            return f"{path}?point={quote(point)}"
        return path

    @app.post("/pace", response_class=HTMLResponse)
    async def set_pace(request: Request, pace_ms: int = Form(0)) -> Response:
        """Choose how slowly a run plays.

        **Why a product has a deliberate pause in it.** Parsing and chunking are local
        work of a few milliseconds, and against the offline fake providers a whole
        ingest is about twenty — so "watch a document become vectors" is not something
        any polling interval can deliver. The pause is inserted *between* stages and
        never inside one, so every duration, token count and cost stays exactly what it
        would have been; the canvas says it is paced while it is. That is the whole of
        what makes it honest enough to ship here.

        A form post with a redirect, so the control works with scripts disabled — and
        so the choice survives a reload, which matters when the reason you set it is
        that a room is watching.
        """
        # Back where they were, but only ever to a path on this site. `Referer` is a
        # header, so it is the caller's to set: reflecting it whole would make this an
        # open redirect, which is a real one however small the feature.
        response = RedirectResponse(_back_here(request), status_code=303)
        response.set_cookie(
            _PACE_COOKIE,
            str(max(0, min(MAX_PACE_MS, pace_ms))),
            samesite="lax",
            max_age=resolved.server.session_token_ttl_seconds,
        )
        return response

    @app.post("/websearch")
    async def set_web_search(request: Request, on: str = Form("")) -> Response:
        """Turn the agent's web route on or off for this browser.

        **What this switch is and is not.** It is permission, not capability: the
        Backend combines it with whether `AXIS_SEARCH__PROVIDER` configured a provider
        at all, so turning it on where none exists reaches nothing. The sidebar only
        draws the control when the Backend reports one is configured, so the two agree
        — but the enforcement is on the server side of that agreement, not in the
        template.

        Off by default and off on anything unparseable. A web call is paid, goes to a
        third party, and carries the prompt-injection exposure of System Design Section
        6.5; the failure direction for a switch like that is "did not search", not
        "searched anyway".

        A form post with a redirect, so it works with scripts disabled — the same
        pattern as `/pace`, and for the same reason: the one control in the sidebar that
        spends money should not need JavaScript.
        """
        # Only ever a path on this site. `Referer` is the caller's to set, so
        # reflecting it whole would make this an open redirect.
        response = RedirectResponse(_back_here(request), status_code=303)
        response.set_cookie(
            _WEB_COOKIE,
            "1" if on == "1" else "0",
            samesite="lax",
            max_age=resolved.server.session_token_ttl_seconds,
        )
        return response

    @app.post("/feedback")
    async def record_feedback(
        request: Request,
        trace_id: str = Form(""),
        strategy: str = Form(""),
        reason: str = Form(""),
        note: str = Form(""),
    ) -> Response:
        """Record that an answer was wrong, against the run that produced it.

        **`trace_id` is the whole point.** A report that says only "the answer was
        wrong" is a sentence; one carrying the trace id is a run you can reopen at
        `/trace?id=…` and read stage by stage — which retrieval returned, what the
        prompt was, what the model did with it. That is the difference between
        feedback and a complaint, and it is why this is a control on the answer
        rather than a mail link.

        **Where it goes is a structured log line, and that is a deliberate floor
        rather than a finished feature.** It is durable in the one place that
        survives this deployment — `vercel logs`, or the terminal under
        `python -m axis` — whereas the session store it would otherwise go to is
        `:memory:` in production and is erased with the instance, so a table of
        reports would quietly lose them. A real sink is a database-shaped decision;
        this is honest about being the smallest thing that keeps the report.

        A form post with a redirect, so it works with scripts disabled, like every
        other control here.
        """
        # Bounded before it is logged. `note` is whatever a reporter typed, and a log
        # line is read by a person in a terminal — an unbounded one is a denial of
        # service against the reader, and newlines in it would forge log entries.
        cleaned = " ".join((note or "").split())[:500]
        chosen = reason if reason in FEEDBACK_REASON_IDS else "unspecified"
        logger.warning(
            "answer reported as wrong: reason=%s strategy=%s trace_id=%s note=%r",
            chosen,
            (strategy or "unknown")[:40],
            (trace_id or "unknown")[:64],
            cleaned,
        )
        # Back to the page it was reported from — the answer block renders on Run,
        # Compare and Why-agentic — rather than always to `/`. `_back_here` may already
        # carry `?point=`, so the separator is chosen rather than assumed.
        back = _back_here(request)
        joiner = "&" if "?" in back else "?"
        note_text = quote("Thanks — logged against this run's trace.")
        return RedirectResponse(f"{back}{joiner}flash={note_text}", status_code=303)

    @app.post("/cache")
    async def set_cache(request: Request, on: str = Form("")) -> Response:
        """Turn the semantic cache on or off for this browser.

        **The one toggle in the sidebar whose default is on**, and the asymmetry with
        `/websearch` above is the point rather than an inconsistency. A web call
        spends money at a third party and drags a prompt-injection surface in with
        it, so its failure direction has to be "did not search". A cache hit only
        ever *avoids* spending, so the failure direction here is "paid full price" —
        which costs money but cannot be wrong.

        So this exists for the opposite reason to the web switch: not to permit
        something risky, but to *decline* a saving, so an instructor can charge full
        price for a question the class has already asked and show what was being
        saved. Unparseable input therefore means on, where over there it means off.

        A form post with a redirect, so it works with scripts disabled.
        """
        response = RedirectResponse(_back_here(request), status_code=303)
        response.set_cookie(
            _CACHE_COOKIE,
            "0" if on == "0" else "1",
            samesite="lax",
            max_age=resolved.server.session_token_ttl_seconds,
        )
        return response

    @app.post("/corpus")
    async def set_corpus(request: Request, corpus: str = Form("")) -> Response:
        """Switch which of the session's corpora is being searched.

        **The cheapest control in the rail, and deliberately so.** Both corpora stay
        indexed; only the scope retrieval reads changes. Nothing is re-embedded,
        nothing is deleted, and switching back finds everything exactly as it was —
        including the cached answers, which are keyed by scope and were therefore never
        reachable from the other corpus in the first place.

        That last point is why there is no invalidation here. A cached answer is an
        answer about a particular corpus; keying the cache on the session alone would
        have meant either dropping it on every switch or serving a demo-corpus answer,
        with demo-corpus citations, to a question asked against a student's own files.

        Narrowed to a known name on the way in — it addresses an index scope, and an
        open set would let a forged value name an arbitrary one.

        A form post with a redirect, so it works with scripts disabled — the same
        pattern as `/pace` and for the same reason.
        """
        response = RedirectResponse(_back_here(request), status_code=303)
        response.set_cookie(
            _CORPUS_COOKIE,
            corpus if corpus in CORPORA else DEFAULT_CORPUS,
            samesite="lax",
            max_age=resolved.server.session_token_ttl_seconds,
        )
        return response

    @app.post("/corpus/clear")
    async def clear_corpus(request: Request, corpus: str = Form("")) -> Response:
        """Empty one corpus, leaving the other and the session's history intact.

        **The missing half of the upload limit.** A corpus holds five documents and
        there was no way to remove one, so a full corpus could only be recovered by
        Start over — which also throws away the other corpus, the spend readout and
        every recorded run. Reloading the demo set for a second group meant losing the
        first group's trace.

        Distinct from `/reset`, which discards the *session*: this keeps the session id
        and therefore the runs, the conversation and the ledger, and removes only the
        documents of one corpus and the vectors behind them.
        """
        name = corpus if corpus in CORPORA else DEFAULT_CORPUS
        session_id = request.cookies.get(_SESSION_COOKIE)
        token = request.cookies.get(_TOKEN_COOKIE)
        target = _back_here(request)

        if session_id and token:
            client: BackendClient = request.app.state.backend
            await client.clear_corpus(session_id, token=token, corpus=name)
            # The held summary describes documents that may no longer exist, and the
            # held pain-point result describes a run against an index that has changed.
            # Both would otherwise survive on screen as claims about deleted files.
            _SUMMARIES.pop(session_id, None)
            _PAINPOINTS.pop(session_id, None)

        return RedirectResponse(
            f"{target}?flash={quote(f'Cleared the {name} corpus.')}", status_code=303
        )

    @app.post("/conversation/reset")
    async def reset_conversation(request: Request) -> Response:
        """Start a new conversation, keeping the documents and the run history.

        Three things a student might want to throw away, and they are genuinely
        different: the index (`/reset`, so indexing can be watched again), the
        conversation (here), and nothing at all. Offering only the first would mean
        clearing a follow-up chain cost you the corpus and every run on the Trace
        page — trading one story for another.
        """
        session_id = request.cookies.get(_SESSION_COOKIE)
        token = request.cookies.get(_TOKEN_COOKIE)
        target = _back_here(request)

        if session_id and token:
            client: BackendClient = request.app.state.backend
            try:
                await client.start_new_conversation(session_id, token=token)
            except httpx.HTTPError as exc:
                # Degraded, not fatal. Failing to forget is a worse outcome than a
                # 500, but only just — and a student can press it again.
                logger.warning("Could not start a new conversation: %s", exc)
        return RedirectResponse(target, status_code=303)

    @app.post("/narrate/{step_id}")
    async def narrate(request: Request, step_id: str) -> JSONResponse:
        """Explain one step in plain language.

        **A proxy, because the browser cannot call the Backend directly.** The trace
        view pointed `data-narrate` straight at
        `/api/v1/sessions/{id}/trace/{step}/narrate`, which requires
        `Authorization: Bearer <token>` — and the token is in an `httponly` cookie
        that no script can read, so every narration request from the page was a 401.
        The feature was covered by an acceptance test that calls the API with the
        header, so the API half worked and the half a student touches never had.

        The same shape as every other Frontend route: read the session from cookies,
        add the header, forward.
        """
        client: BackendClient = request.app.state.backend
        session_id = request.cookies.get(_SESSION_COOKIE)
        token = request.cookies.get(_TOKEN_COOKIE)
        if not (session_id and token):
            return JSONResponse(
                {"narration": "Start a session first — ask a question or upload a document."},
                status_code=200,
            )

        try:
            body = await client.narrate(session_id, token=token, step_id=step_id)
        except httpx.HTTPError as exc:
            logger.warning("Could not narrate step %s: %s", step_id, exc)
            # 200 with a readable message rather than an error status: the caller
            # renders this into a paragraph, and a failed explanation should read as
            # a sentence rather than as a broken feature.
            return JSONResponse(
                {"narration": "Could not generate an explanation for this step."},
                status_code=200,
            )
        return JSONResponse(body)

    # -- the canvas -------------------------------------------------------

    async def _canvas_context(
        request: Request,
        *,
        strategy: str | None = None,
        stage_id: str | None = None,
        expand: str | None = None,
        since: int = 0,
        document_id: str | None = None,
        documents: list[dict] | None = None,
        phases: tuple[str, ...] = ("index", "query"),
        card_base: str = "/",
        answer_pending: bool = False,
    ) -> dict:
        """The canvas's state: which stages have run, and with which step.

        `phases` chooses which tracks the board draws, and `card_base` is the path a
        card's open/close link points back at. The two travel together: Indexing moved
        to its own page, so an index card has to reopen on `/indexing` rather than on
        the Run page, where its track is no longer drawn.

        Reads the session's whole trace rather than one run, because the two phases
        have different lifetimes — indexing happened when a document was uploaded and
        stays true until the session is reset, while the query stages belong to the
        most recent question. A canvas scoped to one trace would blank the indexing half
        the moment anybody asked anything, which is exactly backwards: those stages are
        *why* the answer is possible.

        **Nothing is expanded unless asked for**, and that default is the whole point of
        the rebuild. Every card already draws its own data, so the resting state of the
        page is the entire pipeline visible at once; expanding is for reading one stage
        closely, not for seeing it at all. `stage_id` is a student clicking a card;
        `expand` is a stage *type* the server chooses — used once, to open the answer
        after a run finishes.

        `since` is the floor for the *answering* stages, and it exists because those
        cards now carry data rather than a label. `_bind_stages` takes the most recent
        step of each type across the session, so while a new question is in flight the
        previous question's search, prompt and answer are still the most recent ones —
        and a canvas refreshed mid-run would fill the answering track with the last
        answer's numbers under the new question. Passing the sequence number the run
        started at drops them, so those cards stay pending until this run fills them.
        The indexing stages are exempt: they describe documents that are still indexed,
        and blanking them would suggest asking a question un-indexes your files.

        `document_id` chooses *which* document the indexing track describes. Absent, it
        is the most recently indexed one — which is what the track always showed, and
        the right default while a class watches an upload happen. See
        `_indexing_for_document` for why the four stages have to move together.

        `documents` is what the session still holds in the active corpus, and it is the
        second half of the same honesty rule: the trace outlives the documents, so after
        "Clear this corpus" the ingest steps are still there and the track would go on
        drawing real parse, chunk, embed and store figures for a file whose vectors are
        gone. Passed in by the callers that have already fetched it, fetched here for
        `/canvas`, which is asked for a redraw rather than on every poll.
        """
        client: BackendClient = request.app.state.backend
        session_id = request.cookies.get(_SESSION_COOKIE)
        token = request.cookies.get(_TOKEN_COOKIE)
        chosen = strategy or request.query_params.get("strategy") or _default_strategy(
            set((await _health_or_degraded(client)).get("available_strategies") or [])
        )

        steps: list[dict] = []
        if session_id and token:
            try:
                steps = await client.trace_steps(session_id, token=token)
            except httpx.HTTPError as exc:
                logger.warning("Could not read the trace for the canvas: %s", exc)

        stages = stages_for(chosen)
        if since:
            # `ingest` is kept alongside the four indexing stages because it is their
            # parent, and `_bind_stages` binds a stage only when its parent is an
            # `ingest` — drop the parent and the whole indexing half disappears with it.
            steps = [
                s
                for s in steps
                if str(s.get("step_type")) in (*INDEXING_STAGES, "ingest")
                or int(s.get("seq") or 0) > since
            ]
        steps = _answering_run_only(steps)
        bound = _bind_stages(steps)

        # The web search, and the Search card when nothing else claimed it.
        #
        # **A `WEB` route emits no `retrieve` step at all** — `_gather` skips the
        # retriever entirely — and the tool call nests under `iterate`, which
        # `_bind_stages` skips because it is not top level. So the Search card used to
        # render `pending` on precisely the runs that had done the most searching,
        # while Augment and Generate beside it showed done. A student who had just
        # watched the router choose the web read that as "it never searched", which is
        # what the canvas was saying.
        #
        # Bound into `retrieve` rather than given a card of its own: the answering
        # track is at its six-card budget (see `AGENTIC_PREFIX` below on why the cache
        # is a band and not a seventh card), and on a `WEB` route the search *is* the
        # retrieval this run performed. On a `BOTH` route `retrieve` is already bound
        # to the document search and keeps it, so `web_step` travels to the template
        # for the card to draw alongside.
        web_step = _web_search_step(steps)
        if web_step is not None:
            bound.setdefault("retrieve", web_step)

        corpus = _corpus(request)
        if documents is None:
            documents = await _documents(client, request, corpus=corpus)
        held = {
            str(d.get("document_id"))
            for d in documents
            if d.get("document_id")
        }

        # How many vectors the index holds *now*, taken before the indexing half is
        # rebound to one document. The band between the two tracks is the index itself
        # and belongs to neither of them — reading it off the selected document's Store
        # step would show what the index held when that document was written, so
        # choosing the first of four documents made the band report the index shrinking.
        # The Store *card* keeps its own figure, which is a true fact about that step.
        #
        # The *active corpus's* newest Store step, not the session's. `store.count` is
        # already scoped, so each corpus's steps carry their own total — but the most
        # recent step in the session may belong to the other corpus, and the band would
        # then report a total for an index this page is not searching.
        index_total = int(
            ((_latest_store_in(steps, corpus) or {}).get("attributes") or {}).get(
                "total_in_index"
            )
            or 0
        )

        # The indexing half, rebound to one document's ingest run.
        chosen_document, indexed_documents = _rebind_indexing(
            bound, steps, document_id=document_id, corpus=corpus, held=held
        )

        # Which card, if any, is open. A step id wins over a stage type, because the id
        # came from a student clicking and the type is only ever the server's default.
        opened: dict | None = None
        if stage_id:
            opened = next((s for s in steps if str(s.get("id")) == stage_id), None)
        elif expand:
            opened = bound.get(expand)

        siblings: list[dict] = []
        if opened and session_id and token:
            siblings = await _siblings(client, session_id, token, opened)

        # The question this run answered, for the Answering track's label. Taken from
        # the first query-phase step that ran rather than held as state: `route` and
        # `decompose` both record the whole question, and for a naive run `retrieve`
        # records it because naive RAG searches for exactly what was asked. Reading it
        # back from the trace means the label cannot disagree with the run it labels.
        # `cache_lookup` is included and comes *first*, because on a hit it is the only
        # step this run produced — every other candidate below belongs to the pipeline
        # the hit skipped. Without it the Answering track would carry a cached run's
        # answer under no question at all.
        asked = None
        for name in (CACHE_STAGE, "rewrite", "route", "decompose", "retrieve"):
            step = bound.get(name)
            if step and step.get("raw_input"):
                asked = str(step["raw_input"])
                break

        cache_step = bound.get(CACHE_STAGE)
        cache_hit = bool(((cache_step or {}).get("attributes") or {}).get("hit"))

        return {
            "stages": stages,
            # Which tracks to draw, and where a card's links point. See the docstring.
            "phases": phases,
            "card_base": card_base,
            "stage_steps": bound,
            "stage": opened,
            # The band at the head of the answering track, and whether it greys the
            # track out behind it.
            "cache_step": cache_step,
            "cache_hit": cache_hit,
            # For the Search card on a `BOTH` route, where `retrieve` is bound to the
            # document search and the web half would otherwise be invisible. On a
            # `WEB` route this is the same step the card is already bound to, and the
            # template draws it once.
            "web_step": web_step,
            "siblings": siblings,
            "sibling_label": _sibling_label,
            "asked": asked,
            # The canvas is swapped in on its own by `axis.js`, so it needs this in its
            # own context rather than inheriting it from the page chrome.
            "pace_ms": _pace(request),
            "selected_strategy": chosen,
            # Which document the indexing track is describing, and which documents can
            # be asked for. The sidebar links only the ones with an ingest run behind
            # them: a document rejected before indexing has no stages to show, and a
            # link that silently fell back to a different document would be worse than
            # no link.
            "selected_document": chosen_document,
            "indexed_documents": indexed_documents,
            "index_total": index_total,
            "STAGE_TITLES": STAGE_TITLES,
            "STAGE_WHY": STAGE_WHY,
            # **The session's last answer, unconditionally.** It used to be attached
            # only when the synthesize card was open, because that card was the only
            # place it was rendered. The answer leads the page now — it is what the
            # student asked for — so gating it on a card being expanded left the
            # headline empty the moment the server stopped auto-expanding that card.
            # `None` on a fresh session, which is what suppresses the block.
            #
            # **Suppressed while a run is in flight**, and that is not cosmetic: the
            # poller replaces the whole fragment every few hundred milliseconds, so an
            # unconditional answer here rendered the *previous* question's answer back
            # over the new run, several times a second. The board showed a settled
            # answer above a freshly-running set of stages — and it beat the client's
            # own attempt to clear it, because the next poll simply put it back.
            "answer": None if answer_pending else _last_answer(session_id),
            "answer_pending": answer_pending,
        }

    @app.get("/canvas", response_class=HTMLResponse)
    async def canvas(
        request: Request,
        stage: str | None = None,
        since: int = 0,
        document: str | None = None,
    ) -> HTMLResponse:
        """The canvas, rendered.

        **The single renderer of stage content**, and the only thing `axis.js` fetches.
        `_pipeline.html` and `axis.js` once drew the same run from two sides and drifted
        twice; the cards carry far more than those nodes did, so a drift here would mean
        a student is shown different numbers live than on reload. A page without
        JavaScript never asks for this — it links to `/?stage=…` and gets the same
        diagram inside a full render.
        """
        return templates.TemplateResponse(
            request=request,
            name="_canvas.html",
            context=await _canvas_context(
                request,
                stage_id=stage,
                since=since,
                document_id=document,
                # Only the Run page polls, and it draws one track. The indexing page
                # changes on an upload, which is a form post that re-renders anyway.
                phases=("query",),
                # `since` is set only by the poller, and the poller only runs while a
                # question is being answered — so this is the one signal available for
                # "a run is in flight" without inventing a second parameter for it.
                answer_pending=since > 0,
            ),
        )

    # -- live trace -------------------------------------------------------

    @app.get("/trace/recent")
    async def trace_recent(request: Request, since_seq: int = 0) -> JSONResponse:
        """Steps recorded since `since_seq`, for the canvas to poll during a run.

        **Why this polls rather than proxying the Backend's SSE stream**, which
        exists, is tested, and would be the obvious choice:

        The Frontend reaches the Backend through `httpx.ASGITransport`, which buffers
        a response body to completion — so an open-ended stream can never be read
        through it. That is documented in `trace_event_stream`'s own docstring, and it
        is a property of the transport, not of the endpoint. And the browser cannot
        connect to the Backend directly instead, because `EventSource` cannot set the
        `Authorization` header that route requires.

        So SSE remains the design and remains correct — it is the mechanism for the
        networked topology System Design Section 6.2 describes, where the two layers
        really are separate services. In the current single-process topology the
        Frontend polls, and at a 400 ms interval over a 2–8 second run that is five to
        twenty requests against an in-process store, visually indistinguishable from
        streaming. Paying a real architectural cost to avoid twenty cheap requests
        would be the wrong trade.

        `since_seq` is what keeps a run's canvas showing only that run: a session
        accumulates every question's steps, and `seq` is monotonic per process.

        **`fingerprint` is what tells the canvas anything moved**, and `since_seq`
        cannot do that job. A step is now written twice — once running, once
        finished — under one id and one `seq`, so the most interesting transition in
        a run is invisible to a filter on `seq`. The fingerprint hashes every step's
        `(id, status)`, so it changes when a stage starts, when it finishes, and
        when a new one appears, and does not change on a poll where nothing
        happened. That last property is the point: the canvas is replaced wholesale
        when it changes, and re-rendering four times a second would restart every
        animation on the page.
        """
        steps = await _trace_or_empty(request)
        return JSONResponse(
            {
                "steps": [s for s in steps if int(s.get("seq") or 0) > since_seq],
                "fingerprint": _fingerprint(steps),
                "max_seq": max((int(s.get("seq") or 0) for s in steps), default=0),
            }
        )

    @app.get("/trace/state")
    async def trace_state(request: Request) -> JSONResponse:
        """The digest alone — what the canvas polls while a run is in flight.

        **Separate from `/trace/recent` because of what polling costs.** The canvas
        needs two things four times a second: has anything changed, and where does this
        run start. That is about fifty bytes. `/trace/recent` answers it by shipping the
        session's entire trace — every prompt and completion of every run — and the
        client throws all of it away. After twenty questions that is 197 KB per poll,
        growing for as long as the session lives.

        The cost is not the bandwidth. A response that takes longer to build and parse
        than the interval between polls means the next poll starts before the last has
        finished, and a browser allows six connections to one host: the pile-up pushes
        the `/canvas` fetches — the ones that actually redraw the page — behind a queue
        of trace payloads, so the run appears to complete in one jump at the end. Which
        is exactly the symptom, and it gets worse the longer a class has been running.

        `/trace/recent` keeps its steps: it is the honest debugging view and a test
        depends on it. Nothing polls it.
        """
        steps = await _trace_or_empty(request)
        return JSONResponse(
            {
                "fingerprint": _fingerprint(steps),
                "max_seq": max((int(s.get("seq") or 0) for s in steps), default=0),
            }
        )

    async def _trace_or_empty(request: Request) -> list[dict]:
        """This session's steps, or none if there is no session or the read failed.

        Degraded rather than raised: the canvas stops filling and the answer still
        arrives on its own request. A dropped poll mid-demo must not put a banner over
        the answer, and a fresh visitor polling before their first question has not
        done anything wrong.
        """
        client: BackendClient = request.app.state.backend
        session_id = request.cookies.get(_SESSION_COOKIE)
        token = request.cookies.get(_TOKEN_COOKIE)
        if not (session_id and token):
            return []
        try:
            return await client.trace_steps(session_id, token=token)
        except httpx.HTTPError as exc:
            logger.warning("Could not read the trace: %s", exc)
            return []

    async def _health_or_degraded(client: BackendClient) -> dict:
        try:
            return await client.health()
        except httpx.HTTPError as exc:
            logger.warning("Could not reach the backend for health: %s", exc)
            return {
                "status": "error",
                "layers": [],
                "available_strategies": [],
                "config_error": (
                    f"The Frontend could not reach the Backend at "
                    f"{frontend_settings.backend_base_url}."
                ),
            }

    return app


_SESSION_COOKIE = "axis_session"
_TOKEN_COOKIE = "axis_token"
# Slow motion, in milliseconds, as chosen by whoever is driving the demo.
#
# A cookie rather than session state, because it is a preference of the person at the
# keyboard and not a property of the workspace: it survives a reset, it does not belong
# beside the spend and the caps in the session record, and putting it there would have
# meant a migration for a display setting. Not `httponly` — nothing secret, and the
# select needs no script to read it.
_PACE_COOKIE = "axis_pace"

# What the sidebar offers. Three settings rather than a checkbox because a room and a
# person reviewing alone want different speeds, and because "off" has to be the default
# and has to be obviously available.
PACE_CHOICES: tuple[tuple[int, str], ...] = (
    (0, "Off"),
    (600, "Slow"),
    (1500, "Slower"),
)
# The same ceiling the API enforces. Repeated here so a nonsense cookie is corrected
# rather than round-tripped into a 422 the student cannot act on.
MAX_PACE_MS = 2000

# Whether this browser has asked to let the agent leave the documents.
#
# A cookie for the same reasons pace is one: it is a choice about how this person wants
# to run the demo, it should survive a reload and a "start over", and it does not belong
# in the session record beside the spend and the caps.
#
# It is *permission*, never capability. Whether a search provider exists at all is
# `AXIS_SEARCH__PROVIDER`, read server-side; the Backend combines the two with `and`, so
# editing this cookie on an install with no provider configured reaches nothing. Off is
# the default, so a forged or absent cookie lands on the cheaper, document-only side.
_WEB_COOKIE = "axis_web"


def _web_search(request: Request) -> bool:
    """Whether this browser has the web route switched on.

    Anything other than an explicit "1" is off. A cookie is user-editable and this one
    decides whether a paid third-party call may happen, so it is read as a whitelist
    rather than as truthiness — `"false"` and `"0"` are both strings a lenient parse
    would have accepted as yes.
    """
    return request.cookies.get(_WEB_COOKIE) == "1"


_CACHE_COOKIE = "axis_cache"


def _cache_enabled(request: Request) -> bool:
    """Whether this browser wants the semantic cache.

    On unless explicitly switched off, which is the reverse of `_web_search` above
    and for a reason worth reading rather than pattern-matching. That one guards a
    paid third-party call, so a mangled cookie must mean *no*. This one guards a
    saving: a mangled cookie meaning yes costs nothing that was not already going to
    be spent, and meaning no would silently disable a feature nobody switched off.
    """
    return request.cookies.get(_CACHE_COOKIE) != "0"


# Which corpus this browser is looking at.
#
# A cookie, like the pace and the two toggles, rather than a column on the session —
# and unlike the conversation watermark, which *is* a fact about the session's history.
# This is a view preference: two people opening the same session should be able to look
# at different corpora without either changing what the other sees, and a display
# setting is not worth a migration.
#
# Validated against `CORPORA` on the way in, because it names an index scope. A forged
# value would address a scope that does not exist — empty, so the harm is nil, but
# "nothing can name a scope we did not define" is cheaper to hold than to reason about.
_CORPUS_COOKIE = "axis_corpus"


def _corpus(request: Request) -> str:
    """The corpus this browser has selected, narrowed to a name we defined.

    Falls back to `mine` rather than `demo`, matching `index_scope`: an unrecognised
    cookie should land on the corpus that is empty until a student fills it, not on one
    holding five documents they did not choose.
    """
    chosen = request.cookies.get(_CORPUS_COOKIE, "")
    return chosen if chosen in CORPORA else DEFAULT_CORPUS


def _corpus_rows(counts: dict[str, int], active: str, limit: int) -> list[dict]:
    """The rail's corpus group: both corpora, what each holds, and which is live.

    Both are always drawn, including an empty one. A toggle that appears only once
    there is something to toggle to is a toggle nobody discovers — and "your documents,
    0" is the row that says uploading is possible without a student having to guess.
    """
    labels = {DEMO_CORPUS: "Demo corpus", DEFAULT_CORPUS: "My documents"}
    return [
        {
            "name": name,
            "label": labels.get(name, name),
            "count": int(counts.get(name, 0)),
            "limit": limit,
            "active": name == active,
            "full": int(counts.get(name, 0)) >= limit,
        }
        for name in CORPORA
    ]


def _session_keys(state: dict, *, corpus: str, limit: int) -> dict:
    """Spread one `_session_state` fetch into the keys the chrome expects.

    A helper rather than a handful of dict lookups at every call site, so a future
    field on the session cannot reach two of the three templates and not the third —
    which is the shape of bug that produced a rail claiming zero turns on the page
    where turns matter most.

    Now that the rail renders on every page, this is also what guarantees the corpus
    group has its data everywhere: a page that forgot it would raise on the first
    `Undefined` comparison rather than quietly drawing an empty group.
    """
    return {
        "session_spend": state["spend"],
        "turn_count": state["turns"],
        "corpus": corpus,
        "corpora": _corpus_rows(state.get("corpora") or {}, corpus, limit),
    }


def _pace(request: Request) -> int:
    """The pace this browser has asked for, in milliseconds.

    Clamped, because a cookie is user-editable and this number decides how long a
    request is held open. The Backend clamps it too — this one keeps a bad value from
    becoming a validation error in front of a class, that one keeps it from mattering.
    """
    try:
        return max(0, min(MAX_PACE_MS, int(request.cookies.get(_PACE_COOKIE, "0"))))
    except (TypeError, ValueError):
        return 0


def _default_strategy(available: set[str]) -> str | None:
    """Preselect the first *built* strategy.

    So the main panel has something to describe on a first visit, and the rail
    does not open with four unselected items and an empty heading. Returns None
    when nothing is built, which the template renders as "pick a strategy".
    """
    return next((s.value for s in Strategy if s.value in available), None)


# Every answered run, per session, keyed by `trace_id` in the order they happened.
#
# **Keyed by run, not by strategy**, and that is the whole of what made the comparison
# misleading. One slot per strategy meant each run overwrote the last, so the page had
# no choice but to pair whatever two runs happened to be most recent — and reported a
# cost ratio between them whether or not they had asked the same question. There was
# nowhere for an earlier run to live, so there was nothing to choose between.
#
# Presentation state for a demo, deliberately not persisted: it is derived entirely
# from data the Backend already owns, and losing it on restart costs a re-ask. Bounded
# on both axes so a long workshop cannot grow it without limit.
#
# The answer text lives here too. It used to sit in a second store because
# `_comparison` spread a run's whole dict into a table column and an `answer` key
# would have ridden along; columns are built by name now, which removes the reason for
# the split and gives *every* run its answer rather than only the newest — which is
# what lets the comparison show what each of the two runs actually said.
_RUNS: OrderedDict[str, OrderedDict[str, dict]] = OrderedDict()
_RUNS_MAX_SESSIONS = 64
_RUNS_MAX_PER_SESSION = 40


# The last summary per session, and which documents produced it.
#
# Held for the same reason the runs above are, and for one more: Summarize is now a page
# in the nav, so it can be *navigated back to* — and a page that discarded its result on
# every visit would charge a student for the navigation, on the one action expensive
# enough for that to show up in the spend readout. One slot per session rather than a
# history: a summary is a statement about the corpus at a moment, and two of them side
# by side compare nothing, which is what the Compare page is for.
_SUMMARIES: OrderedDict[str, dict] = OrderedDict()
_SUMMARIES_MAX_SESSIONS = 64


def _upload_findings(documents: list[dict]) -> list[str]:
    """The two things about an upload a student can act on, and never used to see.

    **What to do about a failure.** `AxisError.detail` is the actionable half — for a
    scanned PDF, that Axis does no OCR and a text-based export will work — and it was
    written, carried into the API payload, and dropped by both surfaces that could have
    shown it. The `message` alone gives a student the diagnosis and no remedy.

    **What an indexed document left behind.** A scan with a typed cover sheet reports
    "1 indexed" and is searchable over one page of twenty; the count is technically
    true and reads as complete.

    Bounded to two findings and truncated, because this becomes a query parameter on a
    redirect and then one line of a banner. Anything longer belongs to the document
    list and the parse card, which is where the full picture lives.
    """
    findings = [
        d["detail"] for d in documents if d.get("status") == "failed" and d.get("detail")
    ] + [d["note"] for d in documents if d.get("note")]
    return [f[:240] for f in findings[:2]]


def _hold_summary(session_id: str, *, summary: dict, selected: set[str]) -> None:
    """Remember the summary on screen and the selection that produced it."""
    _SUMMARIES[session_id] = {"summary": summary, "selected": selected}
    _SUMMARIES.move_to_end(session_id)
    while len(_SUMMARIES) > _SUMMARIES_MAX_SESSIONS:
        _SUMMARIES.popitem(last=False)


# The last pain-point demonstration per session, held for the same reason the summary
# above is: the Why-agentic page is in the nav, so it can be navigated back to, and a
# page that discarded its result on every visit would charge a student two runs for a
# navigation. One slot rather than a history — the point of the page is one
# demonstration read closely, and four half-remembered ones would be a worse version
# of the Compare page.
_PAINPOINTS: OrderedDict[str, dict] = OrderedDict()
_PAINPOINTS_MAX_SESSIONS = 64

# What a pain-point id is allowed to look like when it is reflected back into a URL by a
# rail redirect. See `_back_here` for why this is a shape check and not a membership one.
_POINT_ID = re.compile(r"[a-z][a-z0-9_-]{0,31}")


def _selected_point(points: list[dict], asked: str | None, held: dict) -> str | None:
    """Which of the four is expanded, or `None` for all four closed.

    A card holds its own detail and widens in place to show it, so this decides which
    card is open rather than what a separate pane describes:

    1. `?point=`, when it names a card that exists;
    2. otherwise the card that has a result — so a finished run lands on its own result
       without `run_pain_point` having to pass the selection separately, and so does a
       navigation back to the page;
    3. otherwise **nothing**.

    **Nothing, and no longer the first card.** A default selection made card one look
    privileged among four that are meant to be peers, and it is the state PRD §6 is
    written against: *"when a student opens the pain-point page, then each of the four
    failures is named … beside the mechanism that answers it and a question that exhibits
    it"* — four closed cards, all carrying all three, is exactly that. It is also the
    shortest the page can be, which is what keeps it inside a viewport without scrolling.

    An unrecognised name therefore falls through to nothing open, which is a better
    failure than the old one: a stale bookmark used to silently open a card the reader had
    not asked for. Falling back rather than raising still follows `?id=` on the Trace page
    and `?stage=` on the canvas.
    """
    known = [str(p.get("id")) for p in points if p.get("id")]
    if asked in known:
        return asked
    if str(held.get("point_id") or "") in known:
        return str(held["point_id"])
    return None


def _mechanism_fired(point_id: str, trace: list[dict]) -> bool | None:
    """Whether the mechanism this pain point is about actually did anything.

    **The most important honesty check on the Why-agentic page**, and it exists
    because of what the page shows against the offline fake providers. There, the
    fake LLM cannot classify or split anything, so the router correctly falls back
    to "simple", the decomposer never fires, and an agentic run makes exactly one
    retrieval — the same as the baseline, for about a hundred times the cost.

    A student reading two columns of "1 retrieval" would draw precisely the wrong
    conclusion: not "this needs a real model", but "the mechanism does nothing". The
    numbers are real and the reading is wrong, which is the worst combination a
    teaching tool can produce. So the page states which it is, from the trace.

    `None` for the summarization card, whose fix is not something a query does at
    all — see the template, which sends a reader to the Summarize page instead.
    """

    def steps(kind: str) -> list[dict]:
        return [s for s in trace if str(s.get("step_type")) == kind]

    def attributes(step: dict) -> dict:
        return step.get("attributes") or {}

    if point_id == "compare":
        # Split into more than one part, which is the only thing that changes what
        # gets retrieved. A `decompose` step exists on every agentic run.
        return any(
            int(attributes(s).get("sub_questions") or 1) > 1 for s in steps("decompose")
        )
    if point_id == "infer":
        return any(attributes(s).get("mode") == "hop" for s in steps("iterate"))
    if point_id == "remember":
        return any(attributes(s).get("changed") for s in steps("rewrite"))
    return None


def _remember_pain_point(session_id: str, held: dict) -> None:
    _PAINPOINTS[session_id] = held
    _PAINPOINTS.move_to_end(session_id)
    while len(_PAINPOINTS) > _PAINPOINTS_MAX_SESSIONS:
        _PAINPOINTS.popitem(last=False)


def _session_runs(session_id: str | None) -> list[dict]:
    """This session's answered runs, oldest first."""
    return list(_RUNS.get(session_id or "", {}).values())


def _last_answer(session_id: str | None) -> dict | None:
    """The newest run's answer, for the canvas's Generate card."""
    runs = _session_runs(session_id)
    return runs[-1].get("answer") if runs else None


def _fingerprint(steps: list[dict]) -> str:
    """A short digest of the trace's *shape and state*.

    Hashed rather than sent whole because the canvas polls this several times a
    second and the trace is the largest thing the session holds; the client only
    ever compares it to the previous value.

    `(id, status)` is the pair that matters. Ids catch a new step; statuses catch a
    step going from running to finished, which is the transition the whole live
    canvas exists to show and the one a `seq` watermark structurally cannot see.
    """
    payload = ";".join(
        f"{s.get('id')}:{s.get('status')}"
        for s in sorted(steps, key=lambda s: int(s.get("seq") or 0))
    )
    return hashlib.sha1(payload.encode(), usedforsecurity=False).hexdigest()[:16]


# Stages that legitimately happen more than once, and what a sibling is labelled by.
#
# The rail has room for one node per stage, and both of these run repeatedly for
# entirely different reasons: indexing once per document, retrieval once per
# sub-question. Binding only the last would silently drop the rest — and in both cases
# the dropped ones are the interesting part. An instructor who loads four documents and
# clicks Chunk should not be shown whichever happened to finish last, which for the
# demo set is a one-chunk image caption.
# Retrieval only. The four indexing stages used to be here, offering a chip per document
# inside an opened card — and it never worked: `_bind_stages` binds the *most recent*
# step of each type, so `/?stage=<an earlier document's chunk>` matched no card. The
# board opened, the track compressed, zero cards expanded, and every one of them still
# drew the last document indexed. Choosing a document is now `?document=` on the whole
# track, which moves all four stages together; a chip that moved one of them was the
# wrong shape for the question anyway.
_SIBLING_STAGES = {"retrieve"}


async def _siblings(
    client: BackendClient, session_id: str, token: str, step: dict
) -> list[dict]:
    """The other retrievals in this run, in order, or empty when there is only one.

    Scoped to the step's own `trace_id`: the previous question's searches belong to a
    different run, and listing them alongside would misrepresent what the agent did.

    Indexing used to be here too, scoped to the session so each chip was a document.
    That job belongs to `?document=` now — see `_SIBLING_STAGES`.
    """
    kind = str(step.get("step_type"))
    if kind not in _SIBLING_STAGES:
        return []

    try:
        steps = await client.trace_steps(
            session_id, token=token, trace_id=step.get("trace_id")
        )
    except httpx.HTTPError:
        return []

    kinds = {str(s.get("id")): str(s.get("step_type")) for s in steps}
    matching = sorted(
        (
            s
            for s in steps
            if s.get("step_type") == kind
            # The same rule the rail binds by: a stage is unparented, or parented by
            # an `ingest`. Without it the provider's nested `embed` call would appear
            # as a sibling of the indexing stage it belongs to.
            and (
                not s.get("parent_step_id")
                or kinds.get(str(s.get("parent_step_id"))) == "ingest"
            )
        ),
        key=lambda s: int(s.get("seq") or 0),
    )
    return matching if len(matching) > 1 else []


def _sibling_label(step: dict) -> str:
    """What to call one sibling on its chip.

    A filename for an indexing stage, the sub-question for a retrieval. Both are the
    thing that distinguishes it from its siblings, which is the only job this label
    has.
    """
    attributes = step.get("attributes") or {}
    return str(
        attributes.get("filename")
        or step.get("raw_input")
        or step.get("label")
        or "step"
    )


def _answering_run_only(steps: list[dict]) -> list[dict]:
    """Drop answering steps that belong to any run but the newest.

    **The cache made this necessary, and it is a correctness fix rather than a
    refinement.** `_bind_stages` takes the most recent step of each type across the
    whole session, which was right while every run emitted the same seven or nine
    steps: the newest `retrieve` was necessarily this run's, because this run had
    one. A cache hit emits `cache_lookup` and nothing else — so the newest
    `retrieve`, `augment` and `synthesize` were the *previous* question's, and the
    canvas drew a full pipeline, all nine cards `done`, for a run that never entered
    it. Nine plausible wrong numbers under a fresh question, which is the one thing
    System Design Section 11.1 says this platform must never show.

    `since` could not catch it. That mechanism floors answering stages at the
    sequence a run *started* at, and it is what the live poller has to use because
    mid-run the client does not yet know the run's id — but a cache hit produces
    almost no new steps, so there is nothing above the floor to replace the old ones
    with and they simply survive.

    Scoping by `trace_id` is exact, needs no parameter, and fixes the reloaded page
    as well as the freshly-posted one: the answering half of the canvas describes one
    run, and a run has an identity. Indexing is untouched — those stages describe
    documents that are still indexed, across every run there has ever been.
    """
    answering = [
        s
        for s in steps
        if str(s.get("step_type")) not in (*INDEXING_STAGES, "ingest")
        and s.get("trace_id")
    ]
    if not answering:
        return steps

    newest = max(answering, key=lambda s: int(s.get("seq") or 0))
    run = str(newest.get("trace_id"))
    return [
        s
        for s in steps
        if str(s.get("step_type")) in (*INDEXING_STAGES, "ingest")
        or str(s.get("trace_id")) == run
    ]


def _bind_stages(steps: list[dict]) -> dict[str, dict]:
    """Stage type → the step that most recently ran it.

    **Most recent, not first**, and the two halves want it for opposite reasons. A
    second uploaded document should move the indexing stages on to *its* parse and
    chunk, because that is the one the student just watched. A second question should
    replace the previous question's search and answer, because leaving the old ones
    would put a stale answer under a fresh question.

    `seq` is assigned at step creation, so sorting by it gives start order and the
    last of each type is the latest — which is also why the rail cannot simply take
    whatever arrived last over the wire, since a step is written when it *completes*
    and a parent therefore lands after its own children.

    **A stage is a step with no parent, or one whose parent is an `ingest`.** Not
    "top-level", which was the obvious rule and the wrong one: the four indexing
    stages all run inside `ingest_document`'s own step, so filtering to top-level
    dropped the entire indexing half of the rail. And not "any step", because the
    provider's own `embed` call nests inside a retrieval — binding that would point
    the Embed node at a query when it belongs to indexing.
    """
    kinds = {str(s.get("id")): str(s.get("step_type")) for s in steps}

    bound: dict[str, dict] = {}
    for step in sorted(steps, key=lambda s: int(s.get("seq") or 0)):
        parent = step.get("parent_step_id")
        if parent and kinds.get(str(parent)) != "ingest":
            continue
        bound[str(step.get("step_type"))] = step
    return bound


def _web_search_step(steps: list[dict]) -> dict | None:
    """The most recent web search this run made, wherever in the tree it happened.

    **Found by attribute rather than by step type, and deliberately not by the top-level
    rule `_bind_stages` uses.** A `search_web` step is the provider's own call and
    nests inside the `call_tool` step that chose it; the `call_tool` is the one that
    carries the model's query and the results, which is what a card has to draw. Both
    sit under `iterate`, so neither is top level and neither would ever bind.

    Matched on `web_results_found` as well as the tool name, the same pair Compare
    already counts searches by — a refused call records the tool it was going to use
    and never gets a result count, and a card drawn from it would show a search that
    did not happen.
    """
    found = [
        s
        for s in steps
        if (s.get("attributes") or {}).get("tool") == "search_web"
        and (s.get("attributes") or {}).get("web_results_found") is not None
    ]
    if not found:
        return None
    return max(found, key=lambda s: int(s.get("seq") or 0))


def _latest_store_in(steps: list[dict], corpus: str) -> dict | None:
    """The most recent `store` step belonging to one corpus's ingest runs.

    Found through the trace rather than through an attribute, for the same reason
    `_rebind_indexing` does: `ingest` is the step that carries `document_id` and
    `corpus`, and Parse, Chunk, Embed and Store are identified only by sharing its
    `trace_id`.
    """
    traces = {
        s.get("trace_id")
        for s in steps
        if str(s.get("step_type")) == "ingest"
        and str((s.get("attributes") or {}).get("corpus") or DEFAULT_CORPUS) == corpus
    }
    stores = [
        s
        for s in steps
        if str(s.get("step_type")) == "store" and s.get("trace_id") in traces
    ]
    return max(stores, key=lambda s: int(s.get("seq") or 0)) if stores else None


def _rebind_indexing(
    bound: dict[str, dict],
    steps: list[dict],
    *,
    document_id: str | None,
    corpus: str = DEFAULT_CORPUS,
    held: set[str] | None = None,
) -> tuple[str | None, list[str]]:
    """Point the four indexing cards at one document of the active corpus, in place.

    **Scoped to the corpus, and that is the same rule one level up.** The trace is
    keyed on the session and therefore holds both corpora's ingest runs, so without
    this the track described whichever document was indexed *last* — which, after
    loading the demo set and then uploading your own, is a document the active corpus
    cannot search. Four cards of real parse, chunk, embed and store figures for a file
    no question on the page can reach.

    An ingest step with no `corpus` attribute predates the two-corpus model and is
    treated as the default corpus, which is where a document indexed before it would
    in fact have gone.

    **`held` is the second half of the same rule.** The trace outlives the documents:
    "Clear this corpus" removes the rows and the vectors and keeps the run history, so
    without this the track would go on drawing that document's real parse, chunk, embed
    and store figures for a file no question can reach. `None` means "do not filter",
    for callers that have no document list to check against.

    **The four stages have to move together or not at all.** `_bind_stages` takes the
    most recent step of each type across the session, which is right for the answering
    half and wrong here: with two documents indexed, asking for an earlier one's Chunk
    while Parse, Embed and Store still described the newest would put two documents on
    one track under one filename. That is worse than only ever showing the last —
    numbers that look like one document's and are three documents' — so the whole track
    is rebound from a single `ingest` run, or the stage is dropped.

    **Dropped, not left behind**, when this document never reached a stage: a document
    that failed at parse must show Chunk, Embed and Store *pending*, not the previous
    document's. That is the shape of "here is where it stopped", and it is only true if
    the absent stages are absent.

    An `ingest` step per document is what makes this possible —
    `backend/dispatch.ingest_document` opens a `trace_id` per file, and that step is
    where `document_id` is recorded. Parse and Store do not carry it, so the trace is
    the key rather than the attribute.

    Returns the document actually being shown and every document that has an ingest run,
    oldest first — the sidebar links exactly those.
    """
    ingests = sorted(
        (
            s
            for s in steps
            if str(s.get("step_type")) == "ingest"
            and str((s.get("attributes") or {}).get("corpus") or DEFAULT_CORPUS) == corpus
            and (
                held is None
                or str((s.get("attributes") or {}).get("document_id") or "") in held
            )
        ),
        key=lambda s: int(s.get("seq") or 0),
    )
    available = [
        str((s.get("attributes") or {}).get("document_id"))
        for s in ingests
        if (s.get("attributes") or {}).get("document_id")
    ]
    if not ingests:
        # Cleared, not left behind. `_bind_stages` has already filled these from the
        # most recent ingest in the session, which may belong to the other corpus — and
        # an indexing track drawn for a corpus holding nothing is the same lie as one
        # drawn for the wrong document, told about four documents instead of one.
        for name in INDEXING_STAGES:
            bound.pop(name, None)
        return None, []

    # An unknown id falls back to the newest, for the same reason `/trace?id=` does: the
    # only ways to hold one are a stale link and a bookmark taken before a reset, and in
    # both cases the newest run is what the reader wants.
    chosen = next(
        (
            s
            for s in reversed(ingests)
            if (s.get("attributes") or {}).get("document_id") == document_id
        ),
        ingests[-1],
    )
    scoped = _bind_stages(
        [s for s in steps if s.get("trace_id") == chosen.get("trace_id")]
    )
    for name in INDEXING_STAGES:
        if name in scoped:
            bound[name] = scoped[name]
        else:
            bound.pop(name, None)

    return str((chosen.get("attributes") or {}).get("document_id") or "") or None, available


# How a run is titled, by the step that identifies it.
#
# `synthesize` rather than `retrieve`, and the distinction matters on an agentic run:
# both pipelines set `synthesize.raw_input` to the question the student actually typed,
# while `retrieve.raw_input` is whichever *sub*-question was searched for last. Titling
# a run with a fragment of itself would make the list quietly misrepresent what was
# asked.
_TITLE_STEPS = ("synthesize", "route", "decompose", "retrieve")

# Worst first. A run is labelled by the most serious thing that happened in it, so a
# failure cannot hide behind the successful steps either side of it.
_STATUS_ORDER = ("error", "budget_exceeded", "running", "ok")


def _traces(steps: list[dict], *, now: datetime | None = None) -> list[dict]:
    """Every run in the session, newest first, summarised enough to choose between.

    **Derived from the same steps the page renders**, rather than from a separate
    Backend endpoint. The list and the detail beside it must never disagree about what
    a run was or what it cost, and one read is the cheapest way to guarantee that — the
    same reasoning that keeps `_bind_stages` here.

    A run is a `trace_id`. Ingestion gets one per document, a question gets one, a
    summary gets one; `backend/dispatch.py` opens them all, which is why every path
    into the AI Backend is groupable here whether or not its author thought about it.
    """
    now = now or datetime.now(UTC)
    grouped: dict[str, list[dict]] = OrderedDict()
    for step in sorted(steps, key=lambda s: int(s.get("seq") or 0)):
        trace_id = str(step.get("trace_id") or "")
        if trace_id:
            grouped.setdefault(trace_id, []).append(step)

    traces = [_summarise(trace_id, group, now) for trace_id, group in grouped.items()]
    # Newest first: the run someone just watched is the one they came to read.
    traces.reverse()
    return traces


def _summarise(trace_id: str, group: list[dict], now: datetime) -> dict:
    """One run, as a row in the picker. `group` is in `seq` order."""
    by_type = {str(s.get("step_type")): s for s in group}
    root = group[0]
    kind = str(root.get("step_type"))

    if kind == "ingest":
        attributes = root.get("attributes") or {}
        title = str(attributes.get("filename") or root.get("label") or "a document")
        kind = "index"
    elif kind == "summarize":
        title = "Document overview"
        kind = "summary"
    else:
        titled = next((by_type[t] for t in _TITLE_STEPS if t in by_type), root)
        title = str(titled.get("raw_input") or titled.get("label") or "a question")
        kind = "query"

    statuses = {str(s.get("status")) for s in group}
    return {
        "id": trace_id,
        "kind": kind,
        "title": title,
        # Absent for indexing and summaries, which is what tells the two kinds apart
        # in the list without anyone having to infer it from the title.
        "strategy": next((s.get("strategy") for s in group if s.get("strategy")), None),
        "steps": len(group),
        # **Top-level steps only.** A parent aggregates its children's usage —
        # `synthesize` adds the completion's usage while the provider's nested
        # `generate` step records the very same usage — so summing every step would
        # report double the cost of every LLM call in the run. `_record_run` filters
        # to `top` for exactly this reason, and this figure has to agree with the one
        # the comparison table shows for the same run.
        "cost_usd": sum(
            float(s.get("cost_usd") or 0) for s in group if not s.get("parent_step_id")
        ),
        "status": next((s for s in _STATUS_ORDER if s in statuses), "ok"),
        "when": _ago(root.get("started_at"), now),
        "at": str(root.get("started_at") or ""),
    }


def _ago(started_at: object, now: datetime) -> str:
    """How long ago, in words.

    Relative rather than a clock time because the reader is picking between runs they
    made in the last few minutes, and "14:32:07" answers a question nobody asked. The
    exact timestamp travels alongside as a tooltip. Rendered per request, so it is
    correct when the page is drawn and does not pretend to stay correct after.
    """
    try:
        when = datetime.fromisoformat(str(started_at))
    except (TypeError, ValueError):
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)

    seconds = max(0, int((now - when).total_seconds()))
    if seconds < 45:
        return "just now"
    if seconds < 3600:
        return f"{round(seconds / 60)} min ago"
    if seconds < 86400:
        hours = round(seconds / 3600)
        return f"{hours} hour{'' if hours == 1 else 's'} ago"
    days = round(seconds / 86400)
    return f"{days} day{'' if days == 1 else 's'} ago"


def _record_run(
    session_id: str, *, strategy: str, question: str, answer: dict, trace: list[dict]
) -> None:
    """Pin one completed run's figures for the comparison.

    Everything here is derived from the answer and trace this request already has —
    no extra round trip. The metrics were chosen to answer the one question the
    comparison exists for: what did the extra orchestration *buy*?

    The old set — stages, steps, latency, cost, citations — could not answer it. Both
    strategies routinely cite the same two passages, so the table read as "agentic
    cost twice as much for nothing" while leaving the reader to work out whether that
    was the finding or a measurement error. Counting the work done (retrievals, LLM
    calls, passages considered) and the ground covered (distinct documents cited)
    makes the difference legible either way.
    """
    per_session: OrderedDict[str, dict] = _RUNS.setdefault(session_id, OrderedDict())
    top = [s for s in trace if not s.get("parent_step_id")]

    def _count(step_type: str, steps: list[dict]) -> int:
        return sum(1 for s in steps if s.get("step_type") == step_type)

    synthesize = next(
        (s for s in top if s.get("step_type") == "synthesize"), {}
    )
    considered = (synthesize.get("attributes") or {}).get("passages_before_dedupe")

    # Filenames rather than document ids: the ids are opaque uuids, and the point of
    # this figure is whether a *different source* was reached.
    documents = sorted(
        {c.get("filename", "") for c in (answer.get("citations") or []) if c.get("filename")}
    )

    decompose = next((s for s in top if s.get("step_type") == "decompose"), {})
    route = next((s for s in top if s.get("step_type") == "route"), {})

    # Every web search this run made, wherever in the tree it happened. Counted from
    # the tool steps rather than from the router's decision, because the two can
    # legitimately differ: the router can choose WEB and the agent can then satisfy
    # the question from documents without ever searching, or hit the search cap. The
    # decision is an intention; this is what actually happened.
    searches = sum(
        1
        for s in trace
        if (s.get("attributes") or {}).get("tool") == "search_web"
        and (s.get("attributes") or {}).get("web_results_found") is not None
    )

    trace_id = str(answer.get("trace_id") or "")
    per_session[trace_id] = {
        # What the run *was*, as opposed to what it measured. Kept because the
        # comparison is now a choice between runs: without the question there is no way
        # to tell the reader which one they are looking at, and no way for the page to
        # notice that the two selected runs asked different things.
        "trace_id": trace_id,
        "strategy": strategy,
        "question": question,
        "at": (top[0].get("started_at") if top else None) or "",
        "answer": answer,
        # Read from the step the decomposer already records rather than counted from
        # retrievals, which conflates "the question was split into three" with "one
        # sub-question was retried twice". Naive emits no decompose step at all, and
        # 1 is the honest reading of that: it asked one question.
        "sub_questions": (decompose.get("attributes") or {}).get("sub_questions", 1),
        # Only top-level retrievals: one per sub-question. A retrieval nested inside a
        # tool call is the agent retrying, which `iterations` already accounts for.
        "retrievals": _count("retrieve", top),
        "llm_calls": _count("generate", trace),
        "iterations": _count("iterate", top),
        # Falls back to the deduplicated count, which is what a naive run reports —
        # it never dedupes because it only retrieves once.
        "passages": considered
        if considered is not None
        else (synthesize.get("attributes") or {}).get("passages", 0),
        "steps": len(trace),
        "latency_ms": answer.get("latency_ms", 0),
        "cost_usd": answer.get("cost_usd", 0.0),
        "citations": len(answer.get("citations") or []),
        "documents": documents,
        "grounded": bool(answer.get("grounded")),
        # Naive RAG has no router, and "documents" is the honest reading of that: it
        # searched the uploaded files, which is the only thing it can do.
        "source": (route.get("attributes") or {}).get("source", "documents"),
        "searches": searches,
        # Whether any citation came from the web. Read from the citations rather than
        # from the route, for the same reason `searches` is: what the answer is
        # actually built on is the thing the comparison should report.
        "web_cited": any(
            c.get("kind") == "web" for c in (answer.get("citations") or [])
        ),
    }
    # Bounded on both axes: sessions, and runs within a session. A workshop asks a
    # lot of questions, and every one of them now keeps its answer text.
    while len(per_session) > _RUNS_MAX_PER_SESSION:
        per_session.popitem(last=False)
    _RUNS.move_to_end(session_id)
    while len(_RUNS) > _RUNS_MAX_SESSIONS:
        _RUNS.popitem(last=False)


def _comparison(
    session_id: str | None,
    available: set[str],
    chosen: dict[str, str] | None = None,
) -> dict | None:
    """The comparison: one chosen run per strategy, plus ratios and a verdict.

    Returns `None` before any run, so the panel stays hidden until it has something
    to say. A single completed run still returns a table — one filled column beside
    one visibly waiting says "ask the other one" better than a panel that only
    appears once both have run.

    `chosen` maps a strategy value to a `trace_id`. An id that is not a run of that
    strategy is ignored in favour of the default, for the same reason `/trace?id=`
    falls back: the only ways to hold one are a stale link and a bookmark.
    """
    runs = _session_runs(session_id)
    if not runs:
        return None

    chosen = chosen or {}
    # Newest first, which is the order the picker offers them in and the order the
    # default below walks.
    by_strategy: dict[str, list[dict]] = {}
    for run in reversed(runs):
        by_strategy.setdefault(str(run["strategy"]), []).append(run)

    default = _default_pairing(by_strategy)
    selected: dict[str, dict] = {}
    for strategy, options in by_strategy.items():
        wanted = chosen.get(strategy)
        selected[strategy] = next(
            (r for r in options if r["trace_id"] == wanted), default[strategy]
        )

    columns = [
        {
            "strategy": s.value,
            "label": _STRATEGY_LABELS[s],
            "ran": s.value in selected,
            # By name rather than by spreading the run, because a run now carries its
            # answer text and its question, and neither belongs in a table column of
            # otherwise-scalar metrics.
            **{key: selected[s.value].get(key) for key, _, _ in _METRICS},
            **{
                key: selected[s.value].get(key)
                for key in ("trace_id", "question", "documents", "grounded", "web_cited")
            },
            "answer": selected[s.value].get("answer"),
        }
        if s.value in selected
        else {"strategy": s.value, "label": _STRATEGY_LABELS[s], "ran": False}
        for s in DEMO_STRATEGIES
        if s.value in available or s.value in by_strategy
    ]
    done = [c for c in columns if c["ran"]]

    # **Whether the two runs asked the same thing**, and the reason the whole picker
    # exists. A cost ratio between two different questions measures two different
    # pieces of work, not what orchestration costs — so when they differ the numbers
    # stay (they are real) and the verdict goes, because the verdict is the sentence
    # that makes a causal claim.
    questions = {str(c.get("question") or "") for c in done}
    matched = len(questions) <= 1

    return {
        "columns": columns,
        "rows": _comparison_rows(done),
        "verdict": _verdict(done) if matched else None,
        "matched": matched,
        "question": next(iter(questions), "") if matched else "",
        "options": {s: by_strategy.get(s, []) for s in (x.value for x in DEMO_STRATEGIES)},
        "selected": {s: r["trace_id"] for s, r in selected.items()},
        "labels": {s.value: _STRATEGY_LABELS[s] for s in DEMO_STRATEGIES},
    }


def _default_pairing(by_strategy: dict[str, list[dict]]) -> dict[str, dict]:
    """Which run each strategy opens on, before anybody chooses.

    **The newest question that more than one strategy has answered**, rather than the
    newest run of each — which is what the page used to do and is how it came to
    mislead. Ask Q1 naive, Q1 agentic, then Q2 naive, and "newest of each" pairs Q2
    against Q1 and prints a cost ratio between two unrelated pieces of work. Walking
    questions newest-first and taking the first that two strategies share makes the
    page a valid comparison on arrival rather than one the reader has to repair.

    With nothing shared it falls back to the newest of each, and the mismatch banner is
    then doing the work.

    `by_strategy` lists are newest first.
    """
    newest = {strategy: options[0] for strategy, options in by_strategy.items() if options}

    ordered = sorted(
        (run for options in by_strategy.values() for run in options),
        key=lambda r: str(r.get("at") or ""),
        reverse=True,
    )
    for run in ordered:
        question = run.get("question")
        answered = {
            strategy: next((r for r in options if r.get("question") == question), None)
            for strategy, options in by_strategy.items()
        }
        shared = {s: r for s, r in answered.items() if r is not None}
        if len(shared) > 1:
            return {**newest, **shared}
    return newest


# Which metrics the table shows, in order, and how each is rendered. A table rather
# than markup so the row set is one list to change — the previous version repeated the
# formatting per column in the template, which is how a cost came to be shown at five
# decimals in one place and six in another.
_METRICS: tuple[tuple[str, str, str], ...] = (
    # First, because it is the mechanism. Everything below is a consequence of the
    # question having been split or not, and the table used to show all the
    # consequences and none of the cause — so "agentic did more work" was visible and
    # *why* was not. A naive run reports 1.
    ("sub_questions", "sub-questions", "int"),
    ("retrievals", "retrievals", "int"),
    # Escalation: the agent going back for another phrasing after a retrieval found
    # nothing. Computed since Milestone 2 and never displayed, which meant the one
    # place agentic cost is *not* fixed overhead was invisible.
    ("iterations", "escalations", "int"),
    # Paid third-party requests. A row of its own rather than folded into `llm calls`
    # because it is the one cost that leaves the machine for something other than a
    # model, and because 0-vs-2 is the clearest possible statement of what the two
    # strategies had access to.
    ("searches", "web searches", "int"),
    ("llm_calls", "llm calls", "int"),
    ("passages", "passages seen", "int"),
    ("latency_ms", "latency", "ms"),
    ("cost_usd", "cost", "usd"),
    ("citations", "citations", "int"),
)


def _comparison_rows(done: list[dict]) -> list[dict]:
    """Per-metric values across strategies, with a ratio against the smaller.

    The ratio is the whole reason this exists. "3593 ms" beside "9749 ms" makes a
    reader do arithmetic to reach "2.7x", and in a demo nobody does it — so the
    headline finding stayed invisible in a table that contained it.
    """
    rows = []
    for key, label, kind in _METRICS:
        values = [c.get(key) or 0 for c in done]
        low, high = (min(values), max(values)) if values else (0, 0)
        rows.append(
            {
                "label": label,
                "kind": kind,
                # Named `cells`, not `values`: Jinja resolves `row.values` to the
                # dict's own `.values` method rather than this key, and the template
                # then iterates a bound method. Same trap waits on `items` and `keys`.
                "cells": [{"strategy": c["strategy"], "value": c.get(key) or 0} for c in done],
                # Only meaningful with two runs to compare, and only when the smaller
                # is non-zero — a naive run that made no tool calls would otherwise
                # produce a division by zero or an "infinity times" ratio.
                "ratio": (high / low) if len(done) > 1 and low > 0 and high != low else None,
            }
        )
    return rows


def _verdict(done: list[dict]) -> str | None:
    """Did the extra work change the answer?

    The one sentence the comparison exists for. Everything above it is evidence; this
    is the finding, and without it the table implied a conclusion without ever
    committing to one.

    Compares the *cited document sets*, because that is the only thing here that is
    actually measured: the same sources reached for more money is a different outcome
    from a source the cheaper path missed. "Agentic paid more and reached the same
    sources" is not a result to soften — it is the lesson, and stating it plainly is
    the point.

    **What it must not say is that the answers are the same.** It used to conclude
    "the extra work did not change the answer" from cited-document-set equality, which
    is a different and much stronger claim: two answers citing the same two documents
    can differ in what they extract, how completely, and how precisely they attribute
    it. Nothing here reads the answer text, so nothing here may characterise it. A
    quality verdict needs the scoring in `ai_backend/evaluation/scoring.py` and a
    golden set behind it — Milestone 3's cross-strategy evaluation report — and until
    then the honest move is to report the sources and let the student compare the two
    answers above, which are on screen precisely so they can.
    """
    if len(done) < 2:
        return None

    cheap, dear = sorted(done, key=lambda c: c.get("cost_usd") or 0.0)
    base = cheap.get("cost_usd") or 0.0
    ratio = ((dear.get("cost_usd") or 0.0) / base) if base else None
    times = f"{ratio:.1f}x the cost" if ratio and ratio > 1 else "a comparable cost"

    # Checked before groundedness, because it changes what every branch below would
    # otherwise mean. PRD Section 6: "when the agentic strategy routes to the web and
    # the naive strategy cannot, the comparison says so explicitly rather than
    # reporting the naive run as having simply found less."
    #
    # Without this, a web-routed answer beside a documents-only one reads as "agentic
    # retrieved better", which is not what happened — it looked somewhere the other
    # one structurally cannot. Conflating the two is how a student concludes
    # *agentic = better retrieval* from evidence that only shows *agentic = more
    # sources*.
    if dear.get("web_cited") and not cheap.get("web_cited"):
        return (
            f"{dear['label']} went to the web, where {cheap['label']} can only search "
            f"your documents — for {times}. That is a difference in *reach*, not in "
            f"retrieval quality: compare them again on a question your documents "
            f"fully answer to see what the orchestration itself buys."
        )

    if not dear.get("grounded") and cheap.get("grounded"):
        return (
            f"{dear['label']} found nothing to cite where {cheap['label']} did, for "
            f"{times}. The extra orchestration did not help on this question."
        )
    if not cheap.get("grounded") and dear.get("grounded"):
        return (
            f"{dear['label']} answered where {cheap['label']} found nothing, for "
            f"{times}. Here the extra work is what produced an answer at all."
        )
    if not cheap.get("grounded") and not dear.get("grounded"):
        return "Neither strategy found anything relevant. The documents do not cover this."

    cheap_docs, dear_docs = set(cheap.get("documents") or ()), set(dear.get("documents") or ())
    if cheap_docs == dear_docs:
        return (
            f"{dear['label']} reached the same {_plural(len(dear_docs), 'source')} for "
            f"{times}. Same ground covered — compare the two answers above to judge "
            f"whether it used it any better."
        )
    if cheap_docs < dear_docs:
        extra = sorted(dear_docs - cheap_docs)
        return (
            f"{dear['label']} reached {_plural(len(extra), 'document')} "
            f"{cheap['label']} missed ({', '.join(extra)}), for {times}."
        )
    if dear_docs < cheap_docs:
        return (
            f"{dear['label']} reached *fewer* sources than {cheap['label']} for "
            f"{times} — worth investigating rather than explaining away."
        )
    return (
        f"The two strategies cited different sources for {times}. Compare the answers "
        f"above and judge which is better grounded."
    )


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _strategy_rows(available: set[str]) -> list[dict]:
    """The strategies the demo offers, baseline first.

    `enabled` is separate from membership on purpose: a strategy the demo advertises
    can still be unrunnable right now, and the rail shows it disabled with a reason
    rather than dropping it. Half a comparison with no explanation is worse than half a
    comparison that says why.
    """
    return [
        {
            "value": s.value,
            "label": _STRATEGY_LABELS[s],
            "is_agentic": s.is_agentic,
            "enabled": s.value in available,
        }
        for s in DEMO_STRATEGIES
    ]


# What the demo advertises — every strategy, since the enum now holds only built ones.
#
# **Deliberately not `available()`**, and that is the whole reason this name still
# exists. `available()` reports what is *registered*, which drops Agentic RAG when the
# configured provider cannot call tools; in that case it should still appear and explain
# itself rather than vanish, leaving a student comparing one strategy against nothing.
# So this is the advertised set and `enabled` carries whether it can run.
#
# Derived from the enum rather than listed by hand, so it cannot drift from it — it was
# a hand-written subset while two graph strategies were declared but unbuilt, and those
# are gone (PRD Section 3).
DEMO_STRATEGIES: tuple[Strategy, ...] = tuple(Strategy)

_STRATEGY_LABELS = {
    Strategy.NAIVE_RAG: "Naive RAG",
    Strategy.AGENTIC_RAG: "Agentic RAG",
}


# ── The stage vocabulary ──────────────────────────────────────────────────────
#
# The two phases of RAG, in the order they happen, and what each stage is *for*.
# The Naive RAG notebook frames the subject exactly this way — "Phase A — Indexing,
# done once, upfront" then "Phase B — Query, done every time a user asks" — and a
# student arriving from it should recognise the shape immediately.
#
# One definition, three consumers: the rail template, `axis.js`, and the detail
# panes. Held here rather than in a template because `axis.js` needs it too and the
# frontend cannot import the AI Backend to get it (layer rule 1).

INDEXING_STAGES: tuple[str, ...] = ("parse", "chunk", "embed", "store")
# `synthesize`, not `generate`: the pipelines emit `synthesize` as the stage and the
# provider's `generate` nests inside it. The node is *titled* "Generate" because that
# is what it does and what a student will call it — the enum name is an internal
# distinction between the stage and the raw call, not one worth teaching.
QUERY_STAGES: tuple[str, ...] = ("retrieve", "augment", "synthesize")
# The agentic strategy puts two decisions in front of the same mechanical core. That
# contrast is the orchestration lesson the platform already taught, and it survives
# intact: same four boxes, two more in front.
AGENTIC_PREFIX: tuple[str, ...] = ("rewrite", "route", "decompose")

# The cache is a *band* at the head of the answering track, not a card, and so it is
# deliberately absent from `AGENTIC_PREFIX`. Two reasons, and the second is the real
# one.
#
# Arithmetic first: the answering track already carries five cards for an agentic
# run and `rewrite` makes six; a seventh does not fit a viewport that must not
# scroll.
#
# But a band is also the *right* drawing. A cache hit means the question never
# entered the pipeline, so the band lights and the rest of the track greys out as
# skipped — the mechanism in one glance. A card would have implied the question
# passed *through* a stage, which is the opposite of what a cache does.
CACHE_STAGE = "cache_lookup"

STAGE_TITLES = {
    "parse": "Parse",
    "chunk": "Chunk",
    "embed": "Embed",
    "store": "Store",
    "cache_lookup": "Cache",
    "rewrite": "Rewrite",
    "route": "Route",
    "decompose": "Decompose",
    "retrieve": "Search",
    "augment": "Augment",
    "synthesize": "Generate",
    "generate": "Generate",
    "search_web": "Web search",
    "iterate": "Reconsider",
    "call_tool": "Tool call",
    "ingest": "Index",
    "summarize": "Summarize",
}

# One sentence per stage, written for someone meeting retrieval for the first time.
#
# Deliberately not generated: the narration feature exists for a *specific* step's
# numbers and costs an LLM call, whereas this is what the stage is for in general and
# must be on screen before anything has run. A student should be able to read the
# whole pipeline's purpose off a fresh page without spending anything.
STAGE_WHY = {
    "parse": "Whatever you uploaded becomes plain text with a location attached, "
             "so nothing after this point has to know it was a PDF.",
    "chunk": "The text is cut into overlapping pieces. Too big and the meaning "
             "blurs; too small and the surrounding context is lost.",
    "embed": "Each piece of text becomes a list of numbers that stands for its "
             "meaning. Similar meanings end up close together.",
    "store": "The numbers are filed alongside their text, ready to be searched. "
             "Nothing is compared yet.",
    "cache_lookup": "Has this been asked before? A close enough match is answered "
                    "from store, and the rest of this track never runs.",
    "rewrite": "The question is resolved before anything is searched for: short "
               "forms expanded, and “it” replaced by what it refers to.",
    "route": "The agent decides where to look, whether the question needs "
             "splitting up, and whether one lookup depends on another.",
    "decompose": "A question with several parts is split, so each part can be "
                 "looked up on its own.",
    "retrieve": "Your question becomes numbers too, and every stored piece is "
                "scored against it. Only the closest ones go forward.",
    "augment": "The passages that survived are pasted into a prompt with your "
               "question. This is the whole of what the model gets to see.",
    "generate": "The model writes an answer from that prompt, citing the passage "
                "numbers it used.",
    "synthesize": "The model writes an answer from that prompt, citing the passage "
                  "numbers it used.",
    "search_web": "A paid search of the public web, used only when the documents "
                  "cannot answer the question.",
    "iterate": "The agent looks at what came back and decides what to try next.",
    "call_tool": "The agent runs a tool it chose, with a query it wrote itself.",
}


# Which step types count as a stage worth naming when the two runs are compared. The
# indexing stages are excluded: both strategies read the same index, so listing them
# would pad both columns identically and bury the difference that matters.
_RUN_STAGES = frozenset(
    {CACHE_STAGE, *AGENTIC_PREFIX, *QUERY_STAGES, "iterate", "call_tool", "search_web"}
)


def stages_for(strategy: str | None) -> list[dict[str, object]]:
    """The rail: both phases, in order, with their titles and purposes.

    **The agentic stages are always emitted, and CSS hides them when a single-shot
    strategy is selected.** Rendering only the selected strategy's stages would have
    been the obvious approach and would have broken a requirement the suite already
    guards: the selector has to respond to a click *without JavaScript*. The radios
    are in the page, so `body:has(...)` can reveal two extra nodes, but nothing can
    make the server re-render on a click that never leaves the browser.

    It is also the better teaching artefact. Choosing Agentic RAG makes two boxes
    appear in front of an otherwise identical strip, before anything has run — which
    is the orchestration lesson stated as geometry rather than as a claim, and it was
    previously only visible after paying for a run.

    Returned as dicts rather than bare names so the template does no lookups, and so
    `axis.js` — which receives the same rendered rail from the server — cannot
    disagree with it about what a stage is called.
    """
    query = [*AGENTIC_PREFIX, *QUERY_STAGES]

    return [
        {
            "type": name,
            "phase": phase,
            "title": STAGE_TITLES.get(name, name),
            "why": STAGE_WHY.get(name, ""),
            # Shown only while an agentic strategy is selected. The flag travels to
            # the template rather than the template testing the name, so adding an
            # orchestration stage is one entry in `AGENTIC_PREFIX`.
            "agentic_only": name in AGENTIC_PREFIX,
        }
        for phase, names in (("index", INDEXING_STAGES), ("query", query))
        for name in names
    ]
