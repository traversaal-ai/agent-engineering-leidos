# Axis ↔ the course material — Alignment Record

*Companion to `Axis_PRD.md` (product scope) and `Axis_System_Design.md` (architecture).
This document maps the course material in `reference/` onto what Axis actually
implements, and records why each difference exists.*

## Why this document exists

Axis is the platform for a course whose material lives in `reference/`. A student meets
that material first, then opens Axis. Every place the platform diverges from it is
therefore a place a student arrives with an expectation the product will either meet or
quietly violate — and a quiet violation in a teaching tool is worse than in a normal
product, because the student has no way to tell which of the two is wrong.

**The alignment target changed, and the sections below are written against both.** This
document originally mapped two notebooks in `docs/reference-notebooks/`. Those were
replaced by the two bundles now in `reference/`, which are the artifacts the cohort was
actually taught from:

| Bundle | What it is | What Axis takes from it |
|---|---|---|
| `reference/module_3_Enterprise RAG/` | The demo this cohort already saw: intro + Naive RAG, as a FastAPI app with four capability levels | The palette and typography (§7); the ACME corpus; and the canonical statement of the **four pain points of naive RAG** (§8) |
| `reference/chapter_07_enterprise_rag/` | The Agentic RAG chapter: router, query rewriter, semantic cache, and an eight-step pipeline wiring them together | The three pillars, ported with their flaws fixed and the fixes recorded (§9) |

**"Takes from" means copied, once, not read at runtime.** No code in Axis opens a path
inside `reference/`; every mention of it in a module is a provenance comment, and the
bundles could be deleted without breaking a thing. The palette became literal values in
`frontend/static/app.css`, the four pain points became strings in
`ai_backend/evaluation/demo.py`, and the ACME corpus became the five files in `data/` at
the repo root — each with its edits applied where it landed and recorded there. The one
on the corpus matters most: see `data/README.md`, because re-copying the originals over
it degrades retrieval silently.

Sections 1–6 were written against the notebooks and are preserved: the notebooks'
*content* survives in these bundles — chapter 07's router is the notebook's router as a
module — so the divergences recorded there still hold. Where a citation named a notebook
it now names the file that carries the same thing.

Divergences are not defects by default. Most of the ones below are Axis being more
rigorous than a teaching notebook can afford to be. But each needs to be a *decision on
record* rather than drift, which is what this file is for.

---

## 1. Naive RAG — aligned, and deliberately stricter

| Notebook | Axis | Why |
|---|---|---|
| Fixed-size character chunker, 300/50 | Recursive chunker, 1200/150, min 100 (`ingestion/chunker.py`) | SD §10 chooses recursive splitting: a fixed window cuts mid-sentence, so the chunk's embedding means something slightly different from the text it came from. |
| `nomic-embed-text-v1.5` via HF transformers, mean-pooled | Provider adapter; `text-embedding-3-small` default, `nomic-embed-text` reachable via Ollama | Providers are swappable by CLAUDE.md. The notebook's own pooling omits nomic's required `search_query:`/`search_document:` prefixes — a notebook flaw Axis does not inherit. |
| Qdrant, in-memory, cosine, 768d | Chroma, cosine (`retrievers/store.py`) | Mandated by CLAUDE.md; the notebook itself lists Chroma among the standard options. Semantics are identical. |
| `k=3`, **no relevance threshold** | `top_k=5`, `min_similarity=0.25`, optional BM25 + RRF hybrid | See §3 — the most behaviourally significant difference in the project. |
| Context interpolated as a Python list repr; prompt says "use the article IDs" but no IDs are supplied | Passages explicitly numbered with source locations; `[n]` resolved back to chunks; out-of-range markers dropped (`pipelines/grounding.py`) | The notebook's citation numbering is fiction — there are no IDs in its prompt to cite. Axis's citations resolve to a real chunk or are discarded. |
| Always calls the LLM | Skips the LLM entirely on empty retrieval; withholds an answer that cites nothing | PRD §6 forbids fabricated citations. See §3. |
| `gpt-4o-mini` | `gpt-4o-mini` default | Aligned. |

**Verdict: aligned.** The two-step shape — retrieve once, generate once — matches the
notebook's definition exactly, and `test_strategy_emits_the_step_types_its_shape_implies`
asserts that `route` and `decompose` never appear in a naive trace. Every divergence above
makes Axis's naive RAG *better* than the notebook's, which has a consequence worth naming
explicitly in §3.

---

## 2. Agentic RAG — a different definition of agency

This is the substantive divergence.

| Notebook | Axis |
|---|---|
| Router = **source selector**: `OPENAI_QUERY` / `10K_DOCUMENT_QUERY` / `INTERNET_QUERY`. Agency = *"where should I look?"* | Router = **complexity classifier**: COMPLEX/SIMPLE + confidence. Agency = *"is this one lookup or several?"* (`agents/router.py`) |
| Three knowledge sources: two Qdrant collections and live web search (SerpApi) | One retriever, one index, one tool |
| The internet route returns **raw snippets — no synthesis, no citations** | Every path synthesises and cites; no web path at all (`agents/tools.py`) |
| No ReAct loop and no iteration. "Tool dispatch" is a Python `dict` lookup on the router's output string | Real tool calling — `ToolSpec`, `ToolCall`, `Role.TOOL` messages — with bounded iterations, and the model chooses the requery phrasing (`agents/react.py`) |
| Sub-query division is an **unfinished assignment**: reference code that returns a raw JSON string and is never wired in | Decomposer implemented, wired, bounded to 4, traced, with a fallback (`agents/decomposer.py`) |
| Router runs on `gpt-4o`, synthesis on `gpt-4`; the naive notebook runs on `gpt-4o-mini` | One configured model for every call in both strategies |
| Router emits an `answer` field (≤5 words), computed and never used | Not carried over — notebook dead code |

### Where Axis is ahead

Three things, and the third is the most transferable lesson in the codebase:

1. **It implements the notebook's open assignment.** Decomposition is left as homework in
   `Agentic_RAG_Notebook.ipynb`; Axis ships it, bounded and traced.
2. **It does real tool calling.** The notebook's "agent" never emits a tool call — a
   string from the router indexes a dict of Python functions. Axis's model receives a tool
   schema, emits a call, and reads the result back as a `Role.TOOL` message.
3. **It holds the model constant across strategies.** The notebooks compare `gpt-4o-mini`
   naive against `gpt-4` + `gpt-4o` agentic, so *their own cost and quality comparison is
   confounded* — some of the difference is the model, not the architecture. Axis uses one
   configured model everywhere, which is what makes the cost delta a measurement rather
   than an artefact. This is worth teaching explicitly: it is the difference between a
   demo and an experiment.

### Where the two now agree

The notebook claims three benefits for agency: **(a)** automatic source selection,
**(b)** real-time information, **(c)** multi-step handling of compound queries. Axis
demonstrated only (c) until source routing landed; it now covers all three.

The convergence kept **both** dimensions rather than adopting the notebook's shape. The
notebook has a single `action` field naming a source and leaves sub-query division as an
assignment; Axis's router emits `SOURCE` *and* `COMPLEXITY`, because a question can be a
single lookup against the web or a three-part question answerable entirely from the
uploaded files — collapsing them would mean inferring each from the other. What it cost
is recorded rather than implied: an amended citation criterion (PRD §6), an accepted
prompt-injection surface (SD §6.5), a per-call cost to cap, and a `cached` provider so a
live demo does not depend on the network.

**Benefit (b) is the one a student is most likely to see fail, and the failure has to
read as a failure of the web rather than of the router.** "Real-time information" is
demonstrated by asking something only the web can answer, which is also the question most
likely to come back with nothing useful. Two things therefore have to hold before that
demo is honest, and neither did at first: the refusal must name the web rather than the
uploaded documents, and the canvas must show the search as a stage that ran. With a
documents-only refusal and a `pending` Search card, a routed, executed, paid web search
was indistinguishable from a router that never fired — and was read that way. See SD §11.1.

**Naive RAG is deliberately excluded from the web route.** A baseline with access to a
source the thing measured against it lacks is not a baseline. This also guards the
lesson: if the web route were the only way Agentic RAG ever won, students would learn
*agentic = has web access* rather than *agentic reasons about retrieval*. PRD §6's
predicted-outcome set keeps at least one documents-only question on which decomposition
alone wins, and `--compare-strategies` fails if that stops being true.

---

## 3. Axis's naive baseline is stronger than the notebook's — and what that hides

Axis's Naive RAG has three guards the notebook's does not:

- a similarity threshold (`min_similarity=0.25`), so retrieval can return nothing;
- the `NO_RELEVANT_CONTENT` sentinel, so the model can decline after seeing the passages;
- withholding of an answer that cites nothing (`pipelines/naive_rag.py`).

**The sentinel had to be scoped once the web route existed, and the reason is worth
teaching.** It read "if they do not contain the answer", which for documents is close to
a binary — a chunk either states the leave policy or it does not. Search snippets are
not: they are approximate about place, silent about date, and truncated mid-sentence. A
search for the current weather in Islamabad returned *"Pagh, Islamabad · Current Weather.
6:49 PM. 90°F. Mostly sunny."* — the asked-for fact, for a district of the asked-for city
— and the model returned the sentinel, because no passage stated the weather *in
Islamabad*. The route, the query and the results were all in the trace; the answer said
nothing had been found, which reads as a broken router rather than a cautious model.

So the prompt now distinguishes *nothing about it* (refuse) from *the thing asked for,
attached to a neighbouring subject or moment* (report it, and name the difference in the
same sentence). The licence is deliberately narrow in exactly that way, because the four
deliberately-unanswerable golden questions depend on the sentinel still firing — nothing
retrieved for "How much does ACME contribute to employee pensions each month?" carries a
monthly contribution figure for anything, so the new rule never engages. Verified rather
than argued: `--strategy agentic_rag` reports `unanswerable handled 4/4` and
`groundedness agreement 100%` with the rule in place.

The notebook's `§12 Limitations of Naive RAG` motivates agency partly on hallucination
risk — *"if the top chunks aren't relevant, there's no way to try again"*. **In Axis that
failure is unobservable**, because naive RAG refuses instead of fabricating. This is the
right safety choice and it removes the notebook's own motivating demo.

Two consequences to state in class rather than discover live:

1. The comparison Axis shows is **cost and ground covered**, not *grounded vs.
   hallucinated*. Both strategies are grounded or both refuse.
2. The gap agentic has to beat is narrower than the notebook implies, because the baseline
   it is measured against is a better baseline.

**Deliberately not built: a switch to disable the threshold.** It would make the
hallucination demo vivid and would give a teaching tool the ability to fabricate a citation
on a projector. If the failure mode is wanted as a number, the honest route is an
evaluation run at `min_similarity=0` reported beside the 0.25 run — the same
"delta is the teaching artifact" pattern SD §10 already uses for hybrid retrieval.

---

## 4. What the platform measures, and what it may therefore claim

Recorded here because the boundary is easy to cross by accident, in a sentence that reads
well.

| Measured | Where | May be claimed |
|---|---|---|
| Cost, latency, LLM calls, retrievals, escalations, sub-questions | `AgentStep` usage, per step | "Agentic cost 2.0x and asked 3 questions where naive asked 1" |
| Which **documents** were cited | `Answer.citations` → filenames | "Reached the same sources" / "reached a document the other missed" |
| Document recall, precision@k, groundedness agreement, content coverage | `evaluation/scoring.py`, against the golden set | Retrieval quality, offline |
| **Answer quality** | *nothing, yet* | **Nothing.** Milestone 3's cross-strategy evaluation report |

The Compare panel's verdict previously concluded *"the extra work did not change the
answer"* from cited-document-set equality. That is a stronger claim than the row above
supports — two answers citing the same two documents can differ in what they extract, how
completely, and how precisely they attribute it — and it is now asserted as an *absence* by
`test_the_verdict_never_claims_the_answers_are_the_same`.

---

## 5. The decomposition ceiling — the notebook's assignment, measured

SD §12 recorded that hand-decomposing the golden set's two relational questions takes
document recall from 0.50 → 1.00 and 0.00 → 1.00. That was a one-off manual experiment,
which meant the strongest evidence for the platform's central claim lived in a sentence in
a document.

It is now a permanent measurement. Compound golden questions carry a `sub_questions` field
— the hand-authored ground-truth decomposition — and
`python -m ai_backend.evaluation --compare-strategies` scores retrieval over the
sub-question union as well as over the whole question. Because splitting from a list needs
no LLM, **this runs offline against the fake providers**, where an agentic run is otherwise
identical to a naive one by construction (a stub router cannot classify and a stub
decomposer cannot split).

Current figures, dense retrieval, fake providers, **re-measured against the ACME
corpus** (the previous set's numbers were 12/15 and 0.773 → 14/15 and 0.909 against the
synthetic handbook fixtures):

```
naive_rag              retrieval 12/20   mean document recall 0.581
decomposition ceiling  retrieval 15/20   mean document recall 0.738

  question                     whole   split   delta
  gfe-delay-remedy              0.50    1.00   +0.50
  key-personnel-risk-owner      0.00    1.00   +1.00
  ceiling-vs-nte                0.00    1.00   +1.00
```

Three for three, where the old set managed two of three — and two of them from **0.00**,
meaning a question naming two things in two documents clears the relevance threshold
against neither when it is embedded whole. That is the comparison pain point as a number
rather than a claim.

### Those `0.00`s were an artefact of the fake embedder, and finding out cost the demo

**The figures above are true only under the fake providers, and the sentence that says so
was doing more work than it looked.** `FakeEmbeddingProvider` is a hashed bag of words
whose cosine similarity *is* literal word overlap, so a blended two-part query scores near
zero against both documents and is filtered by `min_similarity=0.25`. The `0.00` is a
**threshold rejection** — retrieval returned nothing at all — not a ranking failure.

`text-embedding-3-small` does not behave that way. A real semantic embedding of "compare
the master agreement's ceiling with SOW-003's not-to-exceed value" is genuinely close to
*both* documents, clears the threshold comfortably, and returns a chunk from each. So the
baseline scored `document_recall` **1.00**, the ceiling could not exceed 1.00, and every
delta collapsed to `+0.00` by arithmetic. `--compare-strategies` duly reported that
decomposition and the hop chain "bought nothing" and exited non-zero — and it was wrong,
in the most useful way a gate can be: the mechanisms were fine, and the *measure* had
stopped being able to see them.

The fix is `expect_passages` and `fact_recall` (SD §12): the facts an answer cannot be
assembled without, one per side, counted in the retrieved text. On the real embedder, asked
whole, retrieval reaches **neither** of the two figures `ceiling-vs-nte` compares while
landing on both of their documents — 0 of 2 against 2 of 2, on all three decomposition
questions and the hop question. A cleaner result than the numbers above, and the same
retrieval that document recall scored a flat +0.00.

Two lessons worth teaching from this, because both generalise past Axis:

1. **A retrieval figure is meaningless without the embedder it was measured on.** The
   numbers in this section were recorded without that context and were quietly taken as
   properties of the questions. The verdict file now carries the embedding model, `top_k`,
   `min_similarity` and a corpus hash, and a mismatch counts as no measurement (SD §12.1).
2. **Document-level recall is the wrong instrument for a compound question.** It answers
   "did the search go to the right places", which is not what a comparison needs — a
   comparison needs both of the things being compared, and reaching one of them plus some
   other paragraph of the second file scores identically to reaching both.

The absolute recall figures are *lower* than the old set's and that is not a regression:
eight of the twenty questions are designed to fail retrieval offline, because failing is
what their ceilings measure. Reading 0.581 as "retrieval got worse" is a misreading of
the set, in the same way that reading the offline agentic figures as "agentic achieves
nothing" is a misreading of the harness.

The same field is the ground truth for **router quality** on a real-provider run: the
decomposer already records `sub_questions_text`, which can be compared against it directly.

This measurement is what backs the `agentic_wins` label in the predicted-outcome question
set (`evaluation/demo.py`). The label is derived from the golden set's own declarations and
verified by the harness, so a retrieval change that invalidates it fails a test rather than
leaving the product confidently predicting the wrong outcome.

---

## 6. Open divergences

Tracked here so they stay decisions rather than drift.

| Divergence | Status |
|---|---|
| ~~Router classifies complexity, not source~~ | **Closed.** Router emits `SOURCE` (documents / web / both) *and* `COMPLEXITY`, with a model-authored reason |
| ~~No web search~~ | **Closed.** `search_web` is a real tool in the ReAct loop; providers are `serpapi` / `cached` / `fake` / `none` (default) |
| ~~Summarization~~ | **Closed.** Promoted to must-have and built as a mode, not a strategy — `POST /sessions/{id}/summarize` |
| ~~Notebook's chunking lesson (`too large dilutes, too small loses context`) has no on-screen counterpart~~ | **Closed.** The Chunk card draws the chunks as tiles that physically overlap, shaded where they share text, and opening it pages through them with the repeated span marked. One demo fixture was deliberately lengthened so the chunker has something to split — every section had fitted in one chunk, so the overlap the lesson is about never occurred |
| The naive notebook's Exercise 1 — vary `k` and compare — has no equivalent control | Open. `top_k` and `min_similarity` are configuration, not UI. The Search card draws the ranked candidates with the threshold across them, and opening it shows the whole scored list — which teaches the same point statically |
| The notebook's embedding is dense; the offline stand-in is sparse | Recorded rather than open. `FakeEmbeddingProvider` is a hashed bag of words, so the first eight numbers of any vector are zero. The Embed pane therefore also reports how many dimensions carry a value and which are strongest — honest about the head being the head. **The vector lesson is strongest against a real provider**; offline it is legible but flat |
| ~~Notebook teaches Indexing → Retrieval → Generation as three stages; the Axis canvas shows only the query phase~~ | **Closed.** The canvas is two tracks of one diagram, labelled "Indexing — once per document" and "Answering — every question", with the index between them — the notebook's own Phase A / Phase B framing, plus the object both phases touch, which the notebook leaves implicit |
| ~~The two demos look like different products~~ | **Closed.** Axis's palette and type are module 3's, value for value (§7) |
| ~~The four pain points are named in the material and demonstrated nowhere~~ | **Closed.** The *Why agentic* page, backed by four evaluation ceilings (§8) |
| ~~Chapter 07's rewriter and cache have no counterpart in Axis~~ | **Closed**, with four fixes on the way in (§9) |

---

## 7. The palette is module 3's, and why that is an alignment question

Cosmetics are usually not worth a section in a design record. This one is, because the
first thing a student does is recognise or fail to recognise the thing in front of them.

Axis is the *second* demo this cohort meets. The first — `reference/module_3_Enterprise
RAG/frontend/styles.css` — established a pinned light "paper" theme and a specific
colour language, and Axis had a warm-cream palette with a display serif that shared
nothing with it. Two demos of one subject that look like two products make the student
do work that teaches them nothing: deciding whether this is the same system.

So `frontend/static/app.css`'s `:root` block is module 3's values, mapped onto Axis's
own token names by the role each plays. Three things are worth recording rather than
leaving to be rediscovered:

- **The strategy pair is borrowed, not invented.** `--naive` is the accent teal and
  `--agentic` is `#6d5bd0`, which is the violet module 3's Search Lab uses for the
  *second* of two retrieval engines shown side by side. A student who saw that lab reads
  the mapping without being told. Deliberately **not** done: making Agentic the platform
  accent — it would read as the recommended option, and half of what Axis exists to
  teach is the questions on which orchestration is not worth paying for.
- **One family, by weight.** Module 3 is Inter throughout, distinguishing headings by
  weight and negative tracking. Axis's display serif was the single element that made
  the two look unrelated at a glance, so it is gone; the mono stack is now purely system
  faces, which means one fewer thing to vendor rather than two.
- **One value is used differently, and it is a legibility fix.** `--ink-faint` (module
  3's `--muted-2`) measures 2.96:1 against the paper, below WCAG AA for any text size.
  Module 3 uses it for genuinely secondary meta; Axis was using it for `.eyebrow`, which
  is *how a section says what it is* in place of a heading. That label now uses
  `--ink-muted` (4.73:1). No token value diverges — what changed is which of module 3's
  two greys carries a load-bearing label. The old warm palette had the same fault and
  measured **worse** (2.69:1), so this was inherited rather than introduced;
  `test_every_text_colour_in_the_palette_passes_contrast` now computes all of them.

Light is pinned in both, and for the same stated reason: these are shown on projectors
in bright rooms. Neither codebase should grow a `prefers-color-scheme` block.

---

## 8. The four pain points — the material's open question, answered

`reference/module_3_Enterprise RAG/learning-materials/reference/enterprise-rag.md` names
four specific failures of naive retrieval, and its closing **Check** hands one of them
forward by name:

> Is there one pain point that this architecture only partially fixes, one that would
> still benefit from an agent actively deciding to retrieve *again* based on what it just
> found, rather than the router simply picking a knowledge base once up front? Hold onto
> that question, it's exactly where next class's material on Agentic RAG and multi-agent
> systems picks up.

**Axis is that next class**, so this is the alignment obligation the platform was
furthest from meeting. It could always show what orchestration *costs*. It could not show
the shape of the problem orchestration solves — so a student learned a price without
learning what they were buying.

Each of the four is answered by a **different** mechanism, and that is the lesson rather
than a detail of the implementation:

| Pain point (the material's words) | Mechanism | What is measured |
|---|---|---|
| "Retrieval returns chunks, not the whole picture" | Summarize — map-reduce over every chunk | chunks read, of chunks present |
| "Comparison … gets embedded as one single vector and searched once" | Decomposer | document recall, whole question vs split |
| "Implicit data … needs multi-hop reasoning … no mechanism for chaining a second retrieval based on what the first one found" | Router `DEPTH` + the ReAct loop entered on a *successful* retrieval | documents reached, one hop vs the chain |
| "No memory, disconnected dialogue" | Conversation history + the rewriter | the follow-up as typed vs as resolved |

**The four are on screen together**, which is what makes the table above a lesson rather
than a list. The page was a single scrolling column until Milestone 4's last revision, so
a reader met one failure at a time and the "four different mechanisms" point had to be
taken on trust; it is a row of four cards now, each carrying its symptom, its mechanism
and a question that exhibits it, with one open beneath them. See System Design §11.1.

Two divergences from the material, both deliberate:

- **The material says the Agentic Router does not fix multi-hop, and for its own router
  that is true.** Chapter 07's router picks a collection once and its pipeline retrieves
  per sub-query in a flat fan-out — there is no step at which a result informs the next
  query. Axis's ReAct loop can do it, and the change needed was small and precise: the
  loop previously ran *only* when retrieval returned nothing, and stopped the moment a
  tool returned anything. Both are correct for escalation and both are wrong for a hop
  chain, where the first hop succeeding is what makes the second possible.
- **Memory resolves references; it does not carry facts.** See §9.

Everything on that page is a measurement. The predictions are derived from the golden
set's own declarations and verified by `--compare-strategies`, following the rule
`evaluation/demo.py` already established — a hand-written label is a claim in a template
that nothing checks, and the first retrieval change that invalidates it leaves a teaching
tool confidently predicting the wrong outcome.

### 8.1 The card headings are short labels, not the material's own names

`enterprise-rag.md` bolds a name for each of the four under *"Four specific pain points,
each with its own shape"*:

| The material's name | Axis's card heading |
|---|---|
| **1. Struggles to summarize.** | Summarization |
| **2. Comparison is a headache.** | Comparison |
| **3. Implicit data, beyond the obvious.** | Implicit data |
| **4. No memory, disconnected dialogue.** | No memory |

**A divergence, and a deliberate one.** CLAUDE.md's rule is to quote the material rather
than paraphrase it, and these headings do not. The reason is geometry: the material's
names run to 33 characters, which is a sentence rather than a heading, and the four cards
sit side by side at roughly a quarter of the page each — so every one of them would wrap
to two lines in the row's tightest state, on a page whose whole promise is that the four
fit on screen at once.

The rule is met one line down instead, and that is where it matters most. `_SYMPTOMS` in
`ai_backend/evaluation/demo.py` carries the material's **second** sentence for each,
verbatim, directly under the heading — so a student who read the material last week still
meets the wording they read, and what they gain is four words they can scan and an
instructor can point at. The numbering and the order are the material's.

Recorded here because a reader who knows the material will notice, and the next person to
touch these should know it was decided rather than overlooked. Guarded by
`test_each_pain_point_carries_a_short_title`, which quotes the four names it is not using.

### 8.2 Two modes, and why one carries a number and the other does not

That rigour has a cost a student meets immediately: the measurements are claims about the
ACME documents, so the page only *demonstrated* anything on the demo corpus. Someone who
uploaded their own material found four disabled buttons and no way to try the idea on
files they cared about — which is the opposite of what the material asks for, since
*"diagnose the naive RAG failure"* is exercise 3 in
`reference/module_3_Enterprise RAG/learning-materials/study-material/exercises.md`, and
its stated goal is recognising which of the four shapes a given bad answer is.

So the page has two modes, and the difference is stated rather than implied:

| | Demo corpus | Your own documents |
|---|---|---|
| Symptom, mechanism | the same | the same — these are facts about retrieval, not about ACME |
| Question | fixed, from the golden set | **a text box you fill in** |
| Measured | the harness's figure | *"Nothing measured this one — you chose the question, so the shape is demonstrated and the number is not."* |
| Result | both answers, both traces' figures | the same |

**The rule the page rests on is that there is no third state**: every claim is verified,
or is visibly marked as not verified. A card that merely *dropped* its measured line when
the corpus changed would be indistinguishable from a card whose figure nobody bothered to
write, so the unverified mode replaces the number with an explicit statement rather than
an absence.

`_mechanism_fired` does more work in this mode, and the extra work is the exercise. On a
golden question a mechanism that did not fire means the model could not classify — that is
the known cause, and the card says so. On a question a student typed there are two
candidates and the run cannot distinguish them: the question may genuinely not be the
shape the card is about (a single-fact lookup has nothing to decompose, and the router is
*right* to treat it as simple), or the model may be unable to classify it. The card names
both and picks neither. Reporting that the decomposer did not split a question that was
not a comparison is the exercise working, not the page failing.

The two corpora are held at once and a toggle picks the active one, so this is a switch
rather than a trade — a class watches the measured version, then tries the same idea on
its own material, without losing either. See System Design §7 and §13 for the scoping.

---

## 9. Chapter 07's three pillars, ported — and the four things not copied

`reference/chapter_07_enterprise_rag/` implements an agentic router, a query rewriter and
a semantic cache. Axis already had a router, and a stricter one (§2). The other two were
missing outright. Ported, with the reference's own flaws fixed rather than inherited —
each fix is a thing worth showing a class, because each is a bug that would survive
testing:

| chapter 07 | Axis | Why |
|---|---|---|
| Cache grows without bound; the whole JSON file is rewritten on every insert | Bounded LRU, in memory, per session | A workshop is hours long and the file was never the point |
| Reports `1.0 - squared_L2` as "similarity" | Real cosine against a stated threshold | The number is shown to students; it has to be the number it is called |
| Stores only the answer string | Stores the whole `Answer` — text, citations, grounded flag | A cache hit with no provenance cannot satisfy PRD §6's citation criterion |
| Cache is keyed on the raw query, always | Raw when there is no history; the **rewritten** query once there is | "Who signed off on it?" keyed raw would serve a previous *it* — the cache and the memory feature are in direct conflict unless this is decided |
| Router sees the raw query; the rewrite reaches only the decomposer | Everything downstream sees the rewritten query | Routing on text the rewriter has already improved is strictly better information; the reference's ordering looks like an oversight rather than a choice |
| `conversation_history` is accepted and never written back | The Backend persists turns and passes them down | The reference's multi-turn path is defined and not exercised — its notebook never passes a history in |

**Not ported: the router's trivial-`answer` short-circuit.** Chapter 07's router returns
an `answer` field ("AT MOST 5 words if trivially obvious") and its pipeline returns it
directly, skipping retrieval. Axis cannot: an answer produced without retrieval has no
passage to cite, and PRD §6 requires every answer to carry a citation or state that it
found nothing. The notebook this came from computed the field and never used it (§2); the
chapter wires it up, which turns dead code into a citation violation.

**Not ported as written: the cache's role in the cost comparison.** A cached agentic run
costs one embedding, which would make orchestration look free on the Compare page. The
page therefore withholds its cost ratio for any run that was a cache hit — reusing the
withholding it already does for two runs that asked different questions, and for the same
reason: the verdict is the one sentence on that page making a causal claim.

**Kept verbatim: the time-sensitivity keyword gate.** Deliberately over-eager substring
matching, ~40 keywords, and it says so on the card. A cache with no staleness policy
answers a question about today with an answer about last week, and a crude gate that a
student can read in ten seconds teaches that better than a subtle one.

### Memory resolves references; it does not carry facts

The material's memory example is fact accumulation: "Alice has a parrot", then "Bob has
two cats", then "How many pets do Alice and Bob have?" — answered from the conversation.

**Axis will not answer that**, and the reason is its own citation criterion. A fact
recalled from chat history has no passage to cite, so injecting history as evidence
produces exactly the unattributable answer `pipelines/grounding.py` withholds. Module 3
draws the same line in its own prompt — *"the conversation history may be used to
understand WHAT the user is referring to … but never as a source of facts"* — and Axis
enforces it structurally rather than by instruction: history reaches the **rewriter's**
prompt and nothing else, so the resolved question is retrieved for like any other and
every claim in the answer cites a passage.

What a student sees is therefore the reference-resolution half: "What is the
not-to-exceed on SOW-003?" then "Who signed off on it?", with the second question shown
both as typed and as resolved. State the limit in class rather than letting someone find
it: Axis can tell you what *it* refers to, and will decline to add up two things you told
it, because it can only vouch for what it read.
