# Axis — Project Context for Claude Code

## What this project is
Axis is a teaching platform that compares two RAG strategies — **Naive RAG and Agentic
RAG** — side by side on cost, latency, and answer quality, so students see the trade-offs
of agentic orchestration as something measured rather than asserted.

**One variable, held against one baseline.** Both strategies read the same vector index
over the same documents, so the only thing that differs between them is the
orchestration: a router, a decomposer, a query rewriter, a semantic cache, and a bounded
ReAct loop on one side, and a single retrieve-then-answer pass on the other. Every number
the product shows is a comparison of those two, which is why the baseline is guarded as
carefully as the agent (see *Naive RAG never routes* below).

**Graph retrieval is not in scope.** Axis was once specified as a 2×2 of orchestration ×
retrieval, with `LightRAG` and `Agentic LightRAG` filling a graph column. That column was
never built and is now cancelled rather than deferred — removed from the `Strategy` enum,
the docs, and the test suite. Do not reintroduce it, and do not treat a second retriever
as a small addition: it was a third vendor dependency, a second ingestion path, and its
own index-build cost model. PRD Section 3 records it as a non-goal.

## Source of truth — read before proposing any scope change
- `docs/Axis_PRD.md` — problem statement, goals, non-goals, user stories, Given/When/Then
  acceptance criteria, risks/assumptions, open questions, success metrics
- `docs/Axis_System_Design.md` — architecture, C4 diagrams, API surface, data model,
  component trade-offs, milestone roadmap
- `docs/Axis_Notebook_Alignment.md` — how Axis maps onto the course material in
  `reference/`, and why each difference exists. Read this before changing anything about
  the Router, the rewriter, the cache, the naive baseline's guards, or what the Compare
  panel claims: that material is what students meet *first*, so a divergence Axis does
  not state is a divergence a student will read as a bug in one of the two.
- `data/` — **the demo corpus Axis actually indexes.** Five ACME Aerospace documents,
  read by `demo_documents()` in `ai_backend/evaluation/golden.py` and loaded by
  `POST /demo-documents`. Exactly at the five-file upload limit, so a sixth here is a
  file that cannot be loaded. `ai_backend/evaluation/golden/questions.yaml` holds the
  ground truth *about* these, which is why the two are in different places. See
  `data/README.md` before editing either — one document was edited on the way in, and
  re-copying the originals over it silently degrades retrieval.
- `reference/` — **the course material itself, and the alignment target.** Read, not run;
  excluded from ruff for that reason. **Nothing in this codebase opens a path inside it** —
  every mention in code is a provenance comment — so it can be deleted without breaking a
  thing. Two bundles:
  - `reference/module_3_Enterprise RAG/` — the demo this cohort already saw (intro +
    Naive RAG). Where the **palette and typography** (`frontend/static/app.css`) and the
    **ACME corpus** came *from* — both now live in this repo as copies — and, in
    `learning-materials/reference/enterprise-rag.md`, the canonical statement of the
    **four pain points of naive RAG** that the *Why agentic* page exists to demonstrate.
    Quote its wording rather than paraphrasing.
  - `reference/chapter_07_enterprise_rag/` — the Agentic RAG chapter: `agentic_router.py`,
    `query_rewriter.py`, `semantic_cache.py`, `enterprise_pipeline.py`. The three pillars
    Axis must cover. Note what is *not* ported and why — the router's trivial-`answer`
    short-circuit produces an uncited answer, which PRD §6 forbids.
- `docs/*.mermaid` — standalone diagrams referenced by the System Design doc

If an implementation decision reveals the docs are wrong, incomplete, or out of date,
**update the relevant doc first**, then continue — don't let code silently diverge from
the design record.

## Architecture — non-negotiable boundaries
- **Three layers**: Frontend (FastAPI + Jinja2, plus one hand-written `axis.js`), Backend
  (FastAPI application layer), AI Backend (Python package: pipelines, providers, retrievers,
  observability, evaluation)
- Backend contains **no retrieval or generation logic** — it only validates, authenticates,
  rate-limits, and dispatches to the AI Backend
- Backend ↔ AI Backend communication is **in-process Python calls**, not networked
- **Both strategies share one `VectorRetriever`** (Chroma). Sharing it is what makes the
  comparison mean anything: two retrievers would make every difference ambiguous.
- **A pipeline holds a `Retriever`, never a `VectorRetriever`.** The agent loop, router,
  decomposer and rewriter live in `ai_backend/agents/` and take the protocol, so none of
  them can reach into a concrete store. That seam is defined by
  `tests/contract/test_retriever_conformance.py` and used by two test doubles — it is a
  tested boundary, not speculative generality.
- Every `AgentStep` (route, decompose, retrieve, call_tool, synthesize) is emitted through
  the same observability path whichever strategy is running

## Conventions
- **Observability is custom-built**: a `@traced` decorator/context manager wrapping every
  external call, writing structured `AgentStep` events to a session store. Do not add
  Langfuse, LangSmith, OpenTelemetry, or any other tracing framework — this is a
  deliberate teaching choice, not an oversight.
- **The server is the only renderer.** `axis.js` fetches `/canvas` and swaps the HTML
  in; it never builds stage content. `_pipeline.html` and `axis.js` used to draw the same
  run from two sides and drifted twice, and a drift in the cards would mean a student is
  shown different numbers live than on reload. Guarded by
  `test_only_the_server_renders_stage_content`.
- **The canvas is a diagram, and every card draws its own data.** Two tracks joined by
  arrows, both phases on screen at once, each card carrying a miniature of what that
  stage actually produced. It was once a rail of stage names with the data behind a
  click; that passed the acceptance criteria and taught nothing, because a class watching
  from the back of a room cannot click. An opened card grows within its own track and
  never takes the board — burying the diagram to show one pane is how the rail happened.
  Compare and the raw trace are pages, not tabs beside it: a switcher makes the canvas
  one option among four when the canvas is what the product is. Guarded by
  `test_every_stage_draws_its_data_without_being_clicked`.
- **The sidebar is the run's controls, so it lives on the Run page only.** The strategy
  radios carry `form="ask-form"`, which exists nowhere else — on Compare and the raw
  trace they looked live and could not act. The nav names that page *Run*, after what
  happens on it; **canvas** stays the name of the diagram (`/canvas`, `_canvas.html`,
  `.canvasboard`), which is a component and not a word a student needs. Guarded by
  `test_the_run_controls_belong_to_the_run_page`.
- **Summarizing is a page, and it picks its documents.** Four nav pages:
  `Run · Compare · Trace · Summarize` — the first three are the sequence a session
  follows, and Summarize goes after it. It was a button in the rail, which made
  the most expensive action Axis offers a one-click side effect of the document list
  and left its result unreachable once you navigated away. An **empty selection is
  refused without an LLM call** — enforced in `frontend/app.py` and again in
  `ai_backend/summarize.py`; no body still means every document. Guarded by
  `test_summarizing_is_a_page_rather_than_a_control_in_the_rail` and
  `test_an_empty_selection_costs_nothing_at_the_api_too`.
- **The indexing track describes one document, and the sidebar chooses which.**
  `?document=` rebinds all four stages from a single `ingest` run; the default is the
  newest. The four move **together or not at all** — one stage from an earlier document
  beside three from the newest is two documents under one filename — and a stage the
  chosen document never reached is dropped so a failure shows where it stopped. Every
  link out of a card and a hidden field on the ask form carry the selection, because the
  default is a *different* document. Guarded by
  `test_the_indexing_track_never_mixes_two_documents`.
- **Every state the canvas shows is measured, including "running".** A step is written
  when it starts and again when it finishes, under one id, so the running stage is read
  from the trace rather than guessed at by the client. The poller compares a fingerprint
  over every step's `(id, status)` — a `seq` watermark cannot see a status change.
- **Slow motion pauses between stages, never inside a measurement.** Some stages take
  milliseconds, so an instructor can hold the run for a class; the pause sits after the
  `running` write and before the body, so durations, tokens and costs are untouched, and
  the canvas says it is paced while it is. Do not move it inside a timed region, and do
  not add a delay anywhere the UI does not declare.
- **The demo corpus is off by default** (`AXIS_DEMO__DOCUMENTS_ENABLED`), because loading
  it is four paid embedding round trips per click. The labelled example questions go with
  it: they predict outcomes measured against that corpus, so they appear only once those
  documents are indexed.
- **The browser never calls `/api/v1` directly.** The session token is in an `httponly`
  cookie, so a script cannot set the `Authorization` header the API requires. Anything
  the page fetches goes through a Frontend route that reads the cookie — `/narrate/{id}`
  exists for exactly this reason, after every narration request from a page had been
  silently 401ing while its acceptance test passed the header itself.
- **Client-side code is hand-written too, and there is very little of it.** One
  `frontend/static/axis.js`: no framework, no build step, no CDN. HTMX was removed at
  Milestone 2 — it was never actually downloaded, so no script had ever run, and its one
  use swapped a JSON response into the DOM. Everything the demo needs (`EventSource`,
  `fetch`) is native. The page must keep working with JavaScript disabled: the ask form
  posts normally and renders server-side. That is a hard requirement, not a nicety — it is
  what makes the single-machine, nothing-vendored guarantee true.
- **There is no OCR, and a partial extraction must say so.** PDF text is
  `pypdf.extract_text()`; a page with no text layer yields nothing and cannot be indexed.
  Adding OCR needs a rasteriser (PyMuPDF is AGPL and ruled out in `pyproject.toml`) and
  puts a paid vision call on every page of every upload — ask before proposing it. What is
  **not** negotiable is honesty about it: `parse()` returns `ParseResult(blocks,
  unreadable)`, and the count reaches the Parse card, the trace and the upload note,
  because a twenty-page scan that silently indexed one page made the missing text layer
  look like a retrieval bug. See System Design Section 8.1.
- **Providers are swappable**: LLM and embedding calls go through a thin adapter interface
  (OpenAI, Anthropic, Ollama). Never hardcode a specific provider inside a pipeline.
- **Web search is opt-in and snippet-only.** `AXIS_SEARCH__PROVIDER` defaults to `none`,
  and `build_search_provider` returns `None` rather than a no-op — which is load-bearing
  twice: the Router omits `WEB` from its prompt and the ReAct loop omits the tool, so the
  model can never route to a source that does not exist. There is no URL fetch and adding
  one would be a security change, not a feature (System Design Section 6.5).
- **Capability and permission are two different things, combined with `and`.**
  `AXIS_SEARCH__PROVIDER` is the *capability*, read server-side at startup.
  `QueryContext.web_enabled` — the sidebar toggle, carried by the `axis_web` cookie and
  `QueryRequest.web_search` — is the *permission*, and defaults to **off**. Permission
  can only ever narrow, so a forged cookie reaches nothing on an install with no
  provider. `AgenticRagPipeline.run` computes the effective value **once per query** and
  hands the same one to the Router and the loop; they must never be told separately, or
  a run reports a source it never reached. Enforcement is at the call site, not in the
  tool list: with the toggle off the loop holds no web tool, so a hallucinated
  `search_web` lands on the existing unknown-tool branch. Guarded by
  `test_the_toggle_off_refuses_the_call_the_model_makes_anyway`.
- **Naive RAG never routes and never reaches the web.** It is the baseline; a baseline
  with access to a source its comparator lacks is not a baseline.
- Every external call (LLM, embeddings, retrieval, web search) must respect per-session
  cost/rate caps, checked *before* the call is made, not after
- Secrets via environment variables only, loaded server-side in the AI Backend — never
  passed to the Frontend, never logged, never written into a trace shown to students
- Ingestion is one path: shared multi-format parsing feeds chunking, embedding and the
  vector store, and both strategies read what it produced — see System Design Section 8

## Build order — one milestone at a time, in order
Do not start a milestone until the previous one's evaluation slice passes (System Design
Section 14):

1. **Milestone -1** *(done)* — Engineering foundation: config/secrets, error handling,
   provider adapters, three-layer skeleton, the observability library itself
2. **Milestone 0** *(done)* — Naive RAG: ingestion, chunking, vector retrieval, citations,
   golden Q&A set v1
3. **Milestone 1** *(done)* — Agentic RAG: router, decomposition, ReAct loop, tool calling
4. **Milestone 2** *(done)* — The demo surface: live pipeline canvas, streaming trace, the
   two-strategy comparison. No new retrieval or generation capability — this milestone makes
   what already exists *visible*, which is the whole product thesis and had never been on
   screen.
5. **Milestone 3** *(done)* — Three parts, and the first gated the others:
   - **The comparison has to teach both directions.** The platform reliably demonstrated
     what orchestration *costs* and essentially never what it *buys*: offline, a stub
     router cannot classify and a stub decomposer cannot split, so an agentic run was
     identical to a naive one. Compound golden questions now carry a `sub_questions`
     ground truth, and `python -m ai_backend.evaluation --compare-strategies` measures the
     **decomposition ceiling** — the agentic win with the model's ability to decompose
     held out, so it is visible offline. It exits non-zero if splitting stops helping.
     The labelled question set in the UI is derived from those same declarations, so a
     prediction shown to a student is one the harness verifies.
   - **Source routing and a web route.** The router emits `SOURCE` *and* `COMPLEXITY`;
     `search_web` is a real tool. This amended PRD §6's citation criterion — see
     `docs/Axis_Notebook_Alignment.md` before touching it.
   - **Summarizer mode**, Compare mode across both strategies, cross-strategy evaluation
     report.
6. **Milestone 4** *(done)* — The course material's open question: what agentic
   orchestration *buys*, demonstrated rather than claimed. The **query rewriter**
   (resolves a follow-up before anything is searched for), the **semantic cache**
   (bounded, cosine, per session, with a staleness gate), **conversation memory** (a
   watermark over the runs, which is what gives the rewriter something to resolve
   against), and **multi-hop** (the router's `DEPTH` and the loop's hop mode). Each is
   agentic-only, and a test asserts the baseline does not have it. All four land on the
   *Why agentic* page, backed by **four measured evaluation ceilings** so every figure
   shown is one the harness verified.

**Not planned: graph retrieval.** No milestone adds a second retriever. See *What this
project is* above and PRD Section 3 — it is a non-goal, not a backlog item.

Before implementing a milestone: read its section in the System Design doc, propose a
short plan referencing the specific PRD user stories it satisfies, and wait for approval
before writing code.

## Testing
Every must-have user story in PRD Section 5 has a Given/When/Then acceptance criterion in
Section 6. Write an automated test from each one — a milestone isn't done until its
criteria pass as tests, not just informally verified.

## When in doubt
Ask before assuming — especially around cost caps, security scope (see System Design
Section 6.5), and anything listed as an Open Question in PRD Section 8.
