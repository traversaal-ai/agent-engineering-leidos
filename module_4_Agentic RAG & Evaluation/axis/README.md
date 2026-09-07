# Axis

A teaching platform that compares two RAG strategies side by side on cost,
latency, and answer quality — so the trade-offs of agentic orchestration become
measurable rather than abstract.

| | Retrieval | Orchestration |
|---|---|---|
| **Naive RAG** | one vector search over the shared index | none — retrieve, then answer |
| **Agentic RAG** | the same search over the same index | router, decomposer, rewriter, semantic cache, bounded ReAct loop |

**One variable.** Both strategies read the same index over the same documents, with the
same chunking, the same embedding model, the same synthesis prompt and the same cost
caps. So a difference in cost, latency or answer quality between them is attributable to
the orchestration — which is the whole claim the product makes.

Graph retrieval is **not** in scope: it was once specified as a second axis and is now a
stated non-goal. See [`docs/Axis_System_Design.md`](docs/Axis_System_Design.md) §9 for
what that changed and what it did not.

**Design record:** [`docs/Axis_PRD.md`](docs/Axis_PRD.md) (scope, user stories,
acceptance criteria) and [`docs/Axis_System_Design.md`](docs/Axis_System_Design.md)
(architecture, C4 diagrams, API, roadmap). These are the source of truth; code
follows them, and when an implementation decision proves them wrong the doc is
updated first.

---

## Status: Milestone 4 complete

Both strategies work, and the platform now answers the question it was previously
silent on. Upload a PDF, Word document, PowerPoint, spreadsheet, image, or Markdown
file, ask a question, and get an answer with citations you can follow, beside the
trace, the token cost, and the latency that produced it.

What Milestone 4 added is the other half of the comparison. Axis could always show
what orchestration *costs*; it could not show the shape of the problem orchestration
solves, so a student learned a price without learning what they were buying. The
**Why agentic** page now demonstrates each of the four ways plain retrieval fails
with the different mechanism that answers it — a query rewriter, a semantic cache,
conversation memory and multi-hop retrieval, three of which did not exist before —
and every claim on it is bound to a golden question the harness verifies.

| Delivered | Where |
|---|---|
| **Milestone -1** — the foundation | |
| Config and secrets, fail-fast validation | `ai_backend/config/settings.py` |
| Provider adapters (OpenAI, Anthropic, Ollama, fake) | `ai_backend/providers/` |
| Observability library — `@traced`, `AgentStep`, store | `ai_backend/observability/` |
| Error hierarchy → HTTP mapping | `ai_backend/errors.py`, `backend/core/errors.py` |
| Three-layer skeleton, one process | `axis/asgi.py` |
| Sessions, bearer auth, SQLite store | `backend/core/auth.py`, `backend/store/` |
| Per-session cost and rate caps | `backend/core/limits.py` |
| **Milestone 0** — Naive RAG | |
| Shared multi-format parser + zip-bomb guard | `ai_backend/ingestion/` |
| Recursive chunker | `ai_backend/ingestion/chunker.py` |
| `VectorRetriever` — dense and hybrid (BM25 + RRF) | `ai_backend/retrievers/` |
| Image captioning via a narrow `VisionProvider` | `ai_backend/contracts/providers.py` |
| `NaiveRagPipeline` — retrieve, synthesize, cite | `ai_backend/pipelines/naive_rag.py` |
| Golden Q&A set and the evaluation harness | `ai_backend/evaluation/` |
| **Milestone 1** — Agentic RAG | |
| Router, decomposer, bounded ReAct loop with real tool calling | `ai_backend/agents/` |
| **Milestone 2** — the demo surface | |
| Live pipeline canvas, streaming trace, two-strategy comparison | `frontend/` |
| **Milestone 3** — measurement | |
| Decomposition ceiling, labelled questions, source routing, Summarize | `ai_backend/evaluation/`, `ai_backend/summarize.py` |
| **Milestone 4** — the course material's open question | |
| Query rewriter — resolves a follow-up before anything is searched for | `ai_backend/agents/rewriter.py` |
| Semantic cache — bounded, cosine, per session, with a staleness gate | `ai_backend/agents/cache.py` |
| Conversation memory — a watermark over the runs, read by the rewriter | `backend/store/repositories.py` |
| Multi-hop — the router's `DEPTH` and the loop's hop mode | `ai_backend/agents/router.py`, `agents/react.py` |
| Four measured ceilings, gated | `ai_backend/evaluation/runner.py` |
| The *Why agentic* page | `frontend/templates/why.html` |

**Every must-have acceptance criterion passes**, each written as an executable test
against the Given/When/Then it comes from (see [Tests](#tests)).

### What the golden set measures today

```
python -m ai_backend.evaluation --fake --compare-modes
```

| | dense | hybrid |
|---|---|---|
| retrieval pass rate | 60% | 65% |
| mean precision@k | 0.575 | 0.588 |
| mean document recall | 0.581 | 0.675 |
| unanswerable declined | 4/4 | 4/4 |

Three honest notes on that table.

**The absolute numbers are lower than they look, and lower than the previous
corpus's, on purpose.** Eight of the twenty questions are *designed* to fail
retrieval offline: the three compound questions, the multi-hop one and the
conversational one fail by construction, because failing whole and succeeding split
is precisely what their ceilings measure. Reading 0.581 as "retrieval is weak" is a
misreading of the set.

**Hybrid's advantage is now visible offline**, at +0.094 document recall — which the
previous corpus could not show at all. The reason it could not was recorded here as
a property of the fake embedder ("both retrieval arms measure the same signal"), and
that turned out to be only half true: the fake embedder is a hashed bag of words, so
against two topically distinct documents it and BM25 do agree. Against five
interlocking contract documents that share most of their vocabulary they do not —
BM25's term weighting discounts the shared words and finds the rare ones
(`retainage`, `MSA-2026-0417`), and a bag of words cannot. The corpus was the
missing variable, not the provider.

**Compound questions fail in both modes, and that is the recorded baseline** the
decomposition ceiling exists to beat — which it does, on three of three, two of them
from 0.00. See `--compare-strategies`.

---

## Quick start

```bash
python -m pip install -e ".[dev,vector,parsers]"
cp .env.example .env          # then add an API key, or switch to Ollama
python -m axis
```

- UI → <http://127.0.0.1:8000>
- API docs → <http://127.0.0.1:8000/api/v1/docs>
- Health → <http://127.0.0.1:8000/api/v1/health>

**No API key?** Ollama is the zero-key path. Startup validation only demands keys
for the providers actually selected:

```bash
AXIS_LLM__PROVIDER=ollama        AXIS_LLM__MODEL=llama3.1
AXIS_EMBEDDING__PROVIDER=ollama  AXIS_EMBEDDING__MODEL=nomic-embed-text
```

**Load the corpus the demonstrations were measured against.** The *Why agentic*
page will not offer its runs until it is indexed, because every measurement on it is
a claim about those specific documents:

```bash
AXIS_DEMO__DOCUMENTS_ENABLED=true    # then press "Load the demo set" in the sidebar
```

Optionally, vendor Inter rather than letting the page fall back to the platform sans
— see [`frontend/static/VENDOR.md`](frontend/static/VENDOR.md). Nothing is fetched
from a CDN at any point, so a class does not depend on the venue's wifi.

---

## Architecture

```
frontend  ──HTTP/SSE──▶  backend  ──in-process──▶  ai_backend
```

Three layers, one uvicorn process. `axis/asgi.py` mounts the Backend at
`/api/v1` and the Frontend at `/`.

Both halves of that arrangement are deliberate. **Two apps** keeps the
Frontend → Backend hop real HTTP, so the REST/SSE contract is genuinely
exercised and the Frontend has no import path to a provider or a secret.
**One process** means there is a single thing to keep alive during a live demo.

The dependency direction is enforced, not merely documented —
`tests/unit/test_layer_boundaries.py` fails the build if the Frontend imports
another layer, if the Backend reaches the AI Backend outside
`backend/dispatch.py`, or if anyone adds an external tracing framework.

### Where to start reading

1. `ai_backend/contracts/` — the interfaces everything codes against
2. `ai_backend/observability/` — `@traced` and the `AgentStep` store
3. `ai_backend/providers/` — swappable LLM, embedding, and vision adapters
4. `ai_backend/retrievers/vector.py` — the one `Retriever`, shared by both strategies
5. `ai_backend/pipelines/naive_rag.py` — two steps, and why the absent ones matter
6. `ai_backend/pipelines/agentic_rag.py` — the same shape with six stages in front
7. `ai_backend/evaluation/runner.py` — the four ceilings, and why they are one idea
8. `backend/core/limits.py` — the cost cap, and why it runs before dispatch

---

## Tests

```bash
pytest                              # everything
pytest --milestone=0                # just this milestone's slice
python -m ai_backend.evaluation --fake --compare-modes   # golden-set report
ruff check . && mypy ai_backend/contracts
```

Current: **644 passed, 6 skipped, 6 xfailed, 0 failed.**

`tests/acceptance/` holds one module per must-have user story, each test's
docstring quoting its Given/When/Then from PRD Section 6 verbatim. All eight
criteria are written as real executable code; those that cannot pass yet carry
`@pytest.mark.xfail(strict=True)`.

`tests/evaluation/` is the gate CLAUDE.md puts between milestones: it runs the
golden set and asserts floors on retrieval quality, and asserts that every
deliberately-unanswerable question is still declined.

**Strict** matters. When a milestone lands and a feature starts working, a strict
xfail that now passes turns the suite **red** until its marker is deleted. A
`skip` would stay quietly green and the criterion would never be promoted. That
is the mechanism behind *a milestone isn't done until its acceptance criteria
pass as tests* — and it keeps earning its place. It caught two criteria that
already held at Milestone -1, one test passing vacuously, and at Milestone 0 a
hybrid-retrieval test that only passed while the fake embedder was accidentally
bad.

Two guardrails beyond ordinary coverage:

- `test_layer_boundaries.py` — the architecture rules above, as assertions.
- `test_docs_criteria_covered.py` — parses the PRD and fails if a must-have story
  has no acceptance module. Adding a story to Section 5 turns the build red.

The suite is offline by construction: an autouse fixture fails any test that
connects off-machine, so nothing depends on a provider being reachable or on an
LLM answering the same way twice.

---

## Roadmap

Each milestone's evaluation slice must pass before the next begins
(System Design Section 14).

| | | Status |
|---|---|---|
| **-1** | Engineering foundation | ✅ complete |
| **0** | Naive RAG — ingestion, chunking, vector retrieval, citations | ✅ complete |
| **1** | Agentic RAG — router, decomposition, ReAct loop, tools | ✅ complete |
| **2** | The demo surface — live canvas, streaming trace, two-strategy comparison | ✅ complete |
| **3** | Decomposition ceiling + labelled questions, source routing and the web tool, Summarizer mode, Compare mode | ✅ complete |
| **4** | The course material's open question — query rewriter, semantic cache, conversation memory, multi-hop routing, four measured ceilings, the *Why agentic* page | ✅ complete |

**The roadmap ends here.** Two further milestones once existed — `LightRAG` and
`Agentic LightRAG`, filling a graph-retrieval column — and they are **cancelled, not
deferred**: gone from the `Strategy` enum, the docs, the diagrams, the test suite and
the dependency list. System Design §9 records the one argument that was load-bearing
(the graph column justified the `Retriever` protocol and the agent loop's location) and
what replaces it.

One thing genuinely outstanding, and it is a clause rather than a feature: Compare mode
reports latency and cost per strategy but not a quality score — no scorer is wired into
the endpoint. Marked with a strict xfail in `test_ac_compare_mode.py` so that wiring one
in turns the suite green loudly.

---

## Deliberate choices worth knowing

- **Observability is hand-written.** No Langfuse, LangSmith, or OpenTelemetry — a
  test enforces this. Students should be able to read the ~150 lines that produce
  a trace, not trust a framework's output.
- **Providers use raw `httpx`, not vendor SDKs.** The foundation installs and
  tests fully offline, one `respx` mock covers all three adapters identically, and
  the wire protocol is visible.
- **Axis prices its own calls.** Vendors report tokens, not dollars. An unpriced
  model raises rather than costing zero — otherwise the cost cap would silently
  become unlimited.
- **Costs are `Decimal` end to end.** A $2.00 cap compared against a float sum of
  hundreds of tiny costs is not a $2.00 cap.
- **Caps are checked before the call, never after.** Which is why
  `estimate_cost` is part of the `LLMProvider` interface.
- **An uncited answer is withheld.** If no citation survives validation, the
  pipeline returns "I could not find that" rather than an unattributable claim.
  The model's raw output stays visible in the trace, so nothing is hidden — Axis
  simply declines to vouch for it.
- **Chroma is driven with our own embeddings.** Its default embedding function
  downloads an ONNX model, which would break the offline guarantee and make
  embedding cost invisible to the trace.
- **No PyMuPDF.** Faster at PDFs, but AGPL — and PRD Section 4 invites students to
  fork this repo. Every parser dependency is permissively licensed.
