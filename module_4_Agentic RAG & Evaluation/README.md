# Module 4: Agentic RAG & Evaluation

Meet **Axis**, a platform that runs the same question through two RAG strategies and
shows you the bill. Naive RAG and Agentic RAG read the same documents, through the
same index, with the same embedding model and the same synthesis prompt — so the only
thing that differs between the two runs is the orchestration in front of retrieval.

The point of this module is not that agentic RAG is better. It is that **agency has a
price and a payoff, and both are measurable** — Axis is built so you can watch a
question cost three times as much and come back with the same answer, and then watch
the next one cost three times as much and come back with an answer naive RAG could
not reach at all.

That is the lesson Module 3 handed forward. Alex showed you that RAG is string
concatenation with a search step in front of it. Axis shows you what happens when
something gets to *decide* about that search step.

## The two strategies

| Strategy | Retrieval | Orchestration | What you should notice |
|---|---|---|---|
| **Naive RAG** | one vector search over the shared index | none — retrieve, then answer | Two steps in the trace, and no `route` or `decompose` anywhere in it. One LLM call. |
| **Agentic RAG** | the same search, same index | query rewriter, semantic cache, router, decomposer, bounded ReAct loop | Four decisions in front of the same retrieval, then the same synthesis. Three LLM calls in the common case, plus one per escalated sub-question. |

**The order is not fixed, and that is a decision worth pointing at.** A question with
no history behind it is looked up in the cache **as typed**, before anything is spent.
A follow-up is not: "How long is it?" keyed on its own four words would match a
previous "How long is it?" about something else entirely and serve the wrong answer
with a straight face. So when there is history, the rewriter runs *first* and the cache
is keyed on the resolved question. The cache and conversation memory turn out to be
coupled — you cannot safely cache a conversation without resolving it.

**One variable.** Both strategies hold the same `Retriever` instance, typed as the
protocol rather than as the concrete store, so neither can quietly acquire a
capability the other lacks. Naive RAG never routes and never reaches the web — a
baseline with access to a source its comparator lacks is not a baseline.

The absence is tested, not just documented:
`test_strategy_emits_the_step_types_its_shape_implies` asserts that `route` and
`decompose` appear in the agentic trace and appear nowhere in the naive one. The
comparison is visible as **structure**, not as a claim on a slide.

## The things to actually show people

**The canvas** (`/`) is the teaching surface. Two tracks — indexing and answering —
joined by arrows, both phases on screen at once, and **every card draws a miniature of
what that stage actually produced**. Nobody has to click anything, because a class
watching from the back of a room cannot click. There is a slow-motion pace control for
exactly that reason, and the pause sits between stages rather than inside a
measurement, so durations, tokens and costs stay honest while the run is being held.

"Running" is a measured state too, not a client-side guess: a step is written when it
starts and again when it finishes, under one id, so the stage the canvas shows as live
is read from the trace.

**Why agentic** (`/why-agentic`) is the other half of the argument, and the reason this
module exists. Module 3 named four ways naive RAG fails and then handed one of them
forward by name. This page demonstrates all four, each with the *different* mechanism
that answers it — and each card is bound to a golden question the evaluation harness
verifies. A card whose measurement no longer holds says so rather than keeping the
claim.

| # | Pain point | Symptom | The mechanism that answers it |
|---|---|---|---|
| 1 | **Summarization** | Retrieval returns chunks, not the whole picture. | Summarize — map-reduce over every chunk, not the top few |
| 2 | **Comparison** | A comparison gets embedded as one vector and searched once, so the passages skew to one side of it. | The decomposer — one lookup per side, then compare |
| 3 | **Implicit data** | The answer is not stated anywhere. It needs a second retrieval chained off what the first one found. | The router's `DEPTH` decision, and the ReAct loop's hop mode |
| 4 | **No memory** | Every turn is handled in isolation, so a follow-up has nothing to refer to. | Conversation history, resolved by the rewriter |

Four failures, four *different* fixes. A student who leaves believing "agentic is
better" has learned less than one who leaves knowing which failure calls for which
mechanism.

**Compare** (`/compare`) puts two runs of the same question side by side with cost and
latency per strategy. **Trace** (`/trace`) is the raw `AgentStep` stream for any run
this session made. **Summarize** (`/summarize`) is the map-reduce path, on documents
you pick — an empty selection is refused before any LLM call, in two places.

## Setup

```bash
cd axis
python -m pip install -e ".[dev,vector,parsers]"
cp .env.example .env
```

Add an `OPENAI_API_KEY` (embeddings) and an `ANTHROPIC_API_KEY` (answers) to `.env`.
Startup validation only demands keys for the providers actually selected, so **Ollama
is the zero-key path**:

```bash
AXIS_LLM__PROVIDER=ollama        AXIS_LLM__MODEL=llama3.1
AXIS_EMBEDDING__PROVIDER=ollama  AXIS_EMBEDDING__MODEL=nomic-embed-text
```

**Rehearsing with no keys at all.** There is a third provider, `fake` — deterministic,
offline, and what the test suite runs on. Retrieval, routing, the trace, the token
counts and the costs are all real on it; only the answer prose is a stub
(`"This is a fake answer [1]."`). It is the fastest way to confirm the app runs before
a class, and it is not a way to demo answers:

```bash
AXIS_LLM__PROVIDER=fake
AXIS_EMBEDDING__PROVIDER=fake
```

Then load the corpus every measurement on the *Why agentic* page was taken against.
It is **off by default**, because loading it is four paid embedding round trips per
click:

```bash
AXIS_DEMO__DOCUMENTS_ENABLED=true    # then press "Load the demo set" in the sidebar
```

## Run

```bash
python -m axis
```

| | |
|---|---|
| UI | http://127.0.0.1:8000 |
| API docs | http://127.0.0.1:8000/api/v1/docs |
| Health | http://127.0.0.1:8000/api/v1/health |

Three layers, one uvicorn process: the Frontend talks to the Backend over real
HTTP/SSE, the Backend calls the AI Backend in-process. Two apps keeps the REST
contract genuinely exercised; one process means there is a single thing to keep alive
during a live demo.

**Local only, and deliberately.** Nothing is fetched from a CDN at any point, so a
class does not depend on the venue's wifi. Unlike Alex and the Search Lab there is no
deployed URL — Axis holds per-session SQLite and a Chroma index, and the whole design
target is a single machine that works with the network unplugged.

The page also keeps working with JavaScript disabled: the ask form posts normally and
renders server-side. That is a hard requirement rather than a nicety, and it is what
makes the nothing-vendored guarantee true.

## Try these

**Predict before you press Ask.** These three carry a label derived from the golden
set's own ground truth, so the prediction is one the harness verifies rather than one
someone typed into a template.

| Predict | Ask this | Why |
|---|---|---|
| **naive wins** | When is payment due on a correct invoice? | One fact, in one place. Both find it and give the same answer — the agentic run just routed, decomposed, and paid three times as much to get there. |
| **agentic wins** | What is the contractor entitled to if furnished equipment arrives more than thirty days late, and how is it granted? | Two separate things to look up. One blended search finds material for one of them; splitting the question first finds both. This is what the extra cost buys. |
| **both refuse** | How much does ACME contribute to employee pensions each month? | The documents do not cover this. Both say so rather than inventing an answer — agency cannot conjure knowledge that was never indexed. |

There is deliberately **no "tie" question** in the set. Nothing in the corpus spans two
documents without a mechanism that helps, and the code skips a missing outcome rather
than filling it with a placeholder.

Then run the four pain points, which is where the module's argument lives:

| Pain point | Ask this |
|---|---|
| Summarization | Summarize the Sentinel Ground Radar Modernization program. |
| Comparison | Compare the master agreement's overall ceiling with SOW-003's not-to-exceed value, and say which one limits spending on this program. |
| Implicit data | Which contract deliverable is put at risk by the program's highest-exposure risk, and when is it due? |
| No memory | First: *When did the master services agreement take effect?* Then: *How long is it?* |

The last one is the sharpest four words in the corpus. **"How long is it?" contains no
content word at all** — every term in it is among the commonest in English, and the
thing being asked about exists only in the previous turn. It retrieves nothing in
either retrieval mode. Resolving the pronoun is what makes the question findable, and
no amount of retrieval tuning substitutes for it.

## The knowledge base

Five interlocking ACME Aerospace program documents in [`axis/data/`](axis/data/):
master services agreement, statement of work, risk register, and two sets of meeting
notes. **They are the same documents Alex indexes in Module 3**, so a question asked
in Axis lands on material the room already recognises.

> Invented sample data, labelled as such in every file. They exist so the demo answers
> questions a program team would really ask.

They interlock on purpose. A slipped deliverable appears as an action item in the
kickoff notes, an escalation in the status review, and risk R-02 in the register — so
a question can genuinely require using what one document says to know what to look for
in another. That chain is the implicit-data pain point above, and without a real one in
the corpus there would be nothing to demonstrate.

Read [`axis/data/README.md`](axis/data/README.md) before editing them. Every `.md` file
in that directory is loaded except the README, and the demo endpoint carries the same
five-file limit as an upload — so a sixth document turns *Load the demo set* into a
`413`.

## The evaluation half, and where the lesson's metrics come from

The second half of this module teaches Level 3 and Level 4 of the Five Pillars. Axis
computes them:

```bash
cd axis
python -m ai_backend.evaluation --fake --compare-modes        # dense vs hybrid
python -m ai_backend.evaluation --fake --compare-strategies   # naive vs agentic
```

| | dense | hybrid |
|---|---|---|
| retrieval pass rate | 60% | 65% |
| mean precision@k | 0.575 | 0.588 |
| mean document recall | 0.581 | 0.675 |
| unanswerable declined | 4/4 | 4/4 |

**Read that table with the lesson's warning in hand.** Eight of the twenty golden
questions are *designed* to fail retrieval offline — the three compound questions, the
multi-hop one and the conversational one fail by construction, because failing whole
and succeeding split is precisely what the ceilings measure. Reading 0.581 as
"retrieval is weak" is a misreading of the set.

**And then look at what hybrid moves.** The lesson's sharpest Level 3 point is that a
reranker changes *order*, not *membership*, so it can move NDCG@k and MRR but never
Recall@k. Axis has no reranker at all — its hybrid arm is BM25 fused with dense by
Reciprocal Rank Fusion, which changes **membership**. That is why it moves document
recall by +0.094, and it is the same lesson from the other side: the fix for a document
that never made the top k lives upstream in retrieval, not in ranking.

The clearest single case is the golden question `retainage`. "Retainage" appears in one
clause of one document and nowhere else in the corpus. The dense arm finds nothing at
all; the keyword arm returns the right document immediately. No amount of reordering
gets you there.

Level 4 shows up as a hard rule rather than a score: **an uncited answer is withheld.**
If no citation survives validation, the pipeline returns "I could not find that" rather
than an unattributable claim — and the model's raw output stays visible in the trace, so
nothing is hidden. Axis simply declines to vouch for it. All four deliberately
unanswerable questions are declined in both retrieval modes.

The four **measured ceilings** in
[`axis/ai_backend/evaluation/ceilings.json`](axis/ai_backend/evaluation/ceilings.json)
are what every claim on the *Why agentic* page is bound to: decomposition 3/3 questions
improved (two of them from 0.00 to 1.00), hop 1/1 from 0.00, resolution 1/1 from 0.00,
coverage 0.13 → 1.00. `--compare-strategies` exits non-zero if a mechanism stops paying
off, which is what keeps a teaching claim from outliving its measurement.

## What is deliberately absent

Worth saying out loud when you teach this, because the gap between Axis and a
production system is the interesting part:

- **No quality score in Compare mode.** It reports latency and cost per strategy but
  not answer quality — no scorer is wired into the endpoint. Marked with a strict
  `xfail` so that wiring one in turns the suite green loudly. It is the one genuinely
  outstanding item in the project.
- **The semantic cache demonstrates the mechanism, not the selling point, offline.**
  Against the fake embedder — a hashed bag of words — a repeat, a punctuation change
  and a stopword swap all hit, and a genuine paraphrase ("How soon must a correct
  invoice be paid?" against "When is payment due on a correct invoice?") scores 0.447
  and misses. A bag of words has no way to know those mean the same thing, which is the
  entire point of a *semantic* cache. Demo it on real embeddings, or demo it offline and
  say plainly that a paraphrase needs them.
- **No OCR, and a partial extraction says so.** PDF text is `pypdf.extract_text()`; a
  page with no text layer yields nothing and cannot be indexed. The unreadable-page
  count reaches the Parse card, the trace and the upload note — because a twenty-page
  scan that silently indexed one page makes a missing text layer look like a retrieval
  bug.
- **No graph retrieval.** It was once specified as a second axis and is now cancelled
  rather than deferred — gone from the strategy enum, the tests and the dependency list.
- **Observability is hand-written.** No Langfuse, LangSmith or OpenTelemetry, and a test
  enforces this. You should be able to read the ~150 lines that produce a trace rather
  than trust a framework's output.
- **Providers use raw `httpx`, not vendor SDKs**, so the wire protocol is visible and
  the whole thing installs and tests offline.

## Folder map

```
study-material/           the lesson content, organized the way the module was taught
  lesson.md                 RAG recap, Agentic RAG, the Five Pillars, Levels 3 and 4
  key-concepts.md           quick glossary for this module
  exercises.md              hands-on exercises, including two that run Axis
  quiz.md                   14 questions with answers and hints
  recap-and-preview.md      a 15-minute pre-class warm-up
reference/                deep dives the study material points to
  agentic-rag.md             routing, one-shot query planning, tool use, conversation memory
  rag-evaluation.md          the Five Pillars, Levels 3 and 4, with a worked metric example
  glossary.md                the fuller source-of-truth term list
axis/                     the demo: two RAG strategies, measured side by side
  ai_backend/                pipelines, agents, providers, retrievers, observability, evaluation
  backend/                   the application layer — validates, authenticates, caps, dispatches
  frontend/                  the canvas, the Why agentic page, Compare, Trace, Summarize
  data/                      the five ACME documents
  tests/                     one acceptance module per user story, plus the evaluation gate
```

## How to use this folder

| Step | Where | What happens |
|------|-------|--------------|
| 0. Warm up | [`study-material/recap-and-preview.md`](study-material/recap-and-preview.md) | 15-minute refresher on Module 3 and where this module fits |
| 1. Learn the concepts | [`study-material/lesson.md`](study-material/lesson.md) | The full lesson, in class order: Agentic RAG, then evaluation |
| 2. See it run | [`axis/`](axis/) | Both strategies on the same question. The canvas, then *Why agentic* |
| 3. Go deeper | [`reference/`](reference/) | Deep dives on Agentic RAG and on RAG evaluation |
| 4. Practice | [`study-material/exercises.md`](study-material/exercises.md) | Seven exercises — five on paper, two against a running Axis |
| 5. Self-check | [`study-material/quiz.md`](study-material/quiz.md) | 14 questions with answers and hints |
| 6. Quick review | [`study-material/key-concepts.md`](study-material/key-concepts.md), [`reference/glossary.md`](reference/glossary.md) | Fast glossary lookups |

The concepts come first on purpose. Axis is built to be read as well as run — the
pain-point cards quote Module 3's own wording, and the ceilings are what turn "agentic
is better" into a number with conditions attached. Both halves are stronger in that
order, but the demo stands on its own if you are short on time: load the corpus, open
*Why agentic*, and run the four questions.

For the engineering record — architecture boundaries, milestone history, and the
reasoning behind each trade-off — read [`axis/README.md`](axis/README.md) and
[`axis/CLAUDE.md`](axis/CLAUDE.md).
