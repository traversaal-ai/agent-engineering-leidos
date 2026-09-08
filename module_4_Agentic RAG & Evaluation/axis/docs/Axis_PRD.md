# Axis — Product Requirements Document

*Companion document: Axis_System_Design.md covers architecture, diagrams, APIs, and
technical implementation. This PRD covers product scope only.*

---

## 1. Problem Statement

RAG and agentic RAG are usually taught as separate, sequential topics with no direct,
quantified comparison. Students learn "here's naive RAG" in one lesson and "here's
agentic RAG" in another, but rarely see them evaluated against the same question, the
same documents, at the same time — so the trade-offs (cost vs. quality, latency vs.
thoroughness, a single retrieval pass vs. a routed and decomposed one) stay abstract
instead of felt.

This matters now because the class is being built from scratch, with no existing
reference material the instructor can reuse, and because AI systems are probabilistic —
students who only read about "agentic RAG costs more" don't develop real intuition for
*how much more, for what kind of question, and whether it's worth it* until they watch
it happen on their own documents.

Axis is a teaching platform that makes these trade-offs visible and measurable across two
strategies: **Naive RAG and Agentic RAG**.

**Two strategies, one variable.** Both read the same vector index over the same documents,
so the only difference between them is orchestration — a router, a decomposer, a query
rewriter, a semantic cache and a bounded ReAct loop against a single retrieve-then-answer
pass. That is what makes the comparison a measurement rather than a demonstration: a
student can watch Agentic RAG cost 2x and take 3.4x as long as Naive RAG on the same
question, and see the router, the decomposition and the extra retrievals that account for
it — and, on the questions where the baseline fails outright, see what that bought.

---

## 2. Goals

1. Increase the percentage of students who can correctly identify the most
   cost-effective strategy for a given scenario from an estimated 30% (pre-workshop
   baseline) to 80%, measured by an in-class quiz immediately after the hands-on lab.
2. Reduce Compare mode's end-to-end latency (both strategies, one question) to under 45
   seconds, validated before the first live cohort. *(The budget was set when Compare ran
   four strategies concurrently. Two is a weaker requirement against the same number —
   worth revisiting against a real cohort rather than tightening on a guess here.)*
3. Keep median per-student API cost for a full workshop session (ingestion + both
   strategies + 5 Compare runs) under $2, validated in a dry run before launch.
4. Achieve zero unrecoverable failures (crashes requiring a restart) across at least 3
   consecutive full-length dry-run sessions before the course's first live delivery.
5. Increase the share of students who can unprompted name at least one cost/latency/
   quality trade-off for each of the two strategies from near 0% to 90%, measured by a
   post-class survey.

*Note: baseline figures (30%, 0%) are estimates pending confirmation against the
instructor's actual prior-cohort data — see Section 8, Open Questions.*

---

## 3. Non-Goals

- Not a production-scale, multi-tenant SaaS product — no horizontal scaling, load
  balancing, or infrastructure sized beyond one classroom session
- Not a general-purpose enterprise RAG platform — scoped specifically to teaching the
  two-strategy comparison, not to be a reusable product for arbitrary document workloads
- **Not graph RAG, in any form.** The comparison axis is orchestration, and retrieval is
  held fixed at vector search so that the axis means something. Axis was once specified as
  a 2×2 of orchestration × retrieval with LightRAG filling the second column; that is
  cancelled rather than deferred, and the `Strategy` enum, the docs and the tests no
  longer carry it. A second retriever is not a small addition — it is another vendor
  dependency, a second ingestion path, and an index-build cost model with nothing to
  compare it against
- Not covering fine-tuning, RLHF, or model training — retrieval and orchestration only
- Not building production-grade authentication (OAuth/SSO), RBAC, or multi-tenant data
  isolation beyond per-session scoping
- Not optimizing raw latency or cost to a theoretical minimum — optimizing for
  *visibility* into the trade-offs between strategies
- Not supporting real-time collaborative editing of a shared session across students

---

## 4. Users & Use Cases

**The live class demo.** An instructor is midway through explaining why agentic
orchestration doesn't automatically make a RAG system better. Rather than describing the
trade-off, she uploads a fictional company's policy documents, types one multi-part
question, and hits Compare. While both pipelines run, she narrates the trace as it streams
in — pointing out where the router split the question into three parts and retrieved for
each, and why Naive RAG answered only the first part in under two seconds and cited it
confidently, while Agentic RAG took twelve and answered all three. The final comparison
table lands on screen exactly as she reaches the point in her explanation where the
numbers matter.

**The hands-on lab.** A student who's followed the lecture but isn't yet confident about
what the orchestration actually adds opens Axis on his own laptop, uploads a set of course
readings, and starts asking his own questions in each mode individually before trying
Compare. He toggles the trace from raw to narrated view when a step's output confuses
him, and rereads a synthesis step twice before it clicks that the "agentic" answer
actually made two separate retrieval calls where the naive one made one.

**Post-class reference use.** A few weeks after the course, a former student is starting
her own RAG project at work and remembers Axis's `Retriever` interface as a clean example
of how to keep orchestration logic from reaching into a concrete store. She
pulls up the repository, reads the AI Backend module, and adapts the pattern for her own
project rather than starting from a blank file.

---

## 5. User Stories

### Must-have

- As a student, I want to upload up to 5 documents so that I can test retrieval on my own material.
- As a student, I want to choose a strategy (Naive RAG or Agentic RAG) so that I can see
  how each behaves on the same question.
- As a student, I want every answer to include citations so that I can verify it's grounded
  in the documents I uploaded.
- As a student, I want to see a live trace of each step the system takes so that I
  understand how the answer was produced, not just what the answer is.
- As a student, I want a set of example questions labelled with which strategy should win
  so that I can predict the outcome before running it and find out whether I was right.
- As a student, I want the agentic strategy to choose between my uploaded documents and a
  live web search so that I can see a real routing decision, and disagree with it, rather
  than a fixed pipeline.
- As a student, I want to toggle the trace between raw and narrated views so that I can
  choose the level of technical detail that matches what I currently understand.
- As a student, I want to run Compare mode so that I can see latency, cost, and answer
  quality for both strategies side by side on the same question.
- As an instructor, I want per-session cost and rate caps so that one runaway agentic
  loop can't exhaust the class's shared budget mid-session.
- As an instructor, I want the whole system to run reliably on a single machine so that a
  live demo doesn't depend on fragile network or cloud infrastructure.
- As a student, I want a summarizer mode so that I can get a structured overview of my
  documents without having to ask a specific question first.
- As a student with no background in this, I want to watch each stage of indexing and
  answering as it happens — with the actual text and the actual numbers at every stage —
  so that I understand what RAG is doing rather than taking it on trust.
- As a student, I want to read any run this session has made — an upload, an earlier
  question, a summary — and not only the last one, so that I can compare what one
  strategy did against what the other did.
- As a student, I want to see, for each of the four ways naive RAG fails, the specific
  mechanism that answers it, run on the same documents, so that I learn which failure
  calls for which mechanism rather than learning "agentic is better".
- As a student, I want a follow-up question to be understood in the light of what I
  already asked, and to see that the baseline cannot do this, so that I understand what
  conversational memory is and where it stops.
- As a student, I want a reworded repeat of a question I already asked to be answered
  from a cache without a new model call, so that I can see what caching saves and what
  it risks getting wrong.
- As a student, I want to hold the demo corpus and my own documents at the same time and
  switch between them, so that I can watch a demonstration on documents whose outcome is
  already measured and then try the same idea on material I actually care about, without
  losing either.
- As an instructor, I want the hosted demo to sit behind a shared password so that a URL
  I hand to a class cannot be found and used by anyone else to spend the API credits
  behind it.
- As a student, I want to report an answer as wrong against the run that produced it, so
  that a bad answer becomes a run someone can reopen and read stage by stage rather than
  a complaint nobody can act on.

### Should-have

- As an instructor, I want a pre-computed comparison available for the default demo
  documents so that I have a reliable fallback if live generation runs slow in front of
  the class.
- As a student, I want narration generation cached per session so that toggling the
  trace view back and forth doesn't repeatedly re-incur LLM cost.

### Nice-to-have

- As a student, I want to export a Compare run as a shareable report so that I can
  reference it after class without rerunning it.
- As a student, I want to replay a past session's trace step by step so that I can study
  it later at my own pace.
- As an instructor, I want an aggregate view of which strategy "wins" most often across
  the whole class's questions so that I can use it as a live discussion prompt.

---

## 6. Acceptance Criteria

Given/When/Then for each must-have story:

**Upload up to 5 documents**
- Given a valid session, when a student uploads between 1 and 5 files in a supported
  format (PDF, PPTX, XLSX, PNG/JPG), then all files are accepted, parsed, and confirmed
  with a per-file status (success/failed with reason).
- Given a 6th file is uploaded to a corpus already holding 5, when the upload is
  submitted, then it is rejected with a clear "limit reached" message and no partial state change.

*Amended when the corpus became switchable. The limit read "a session already holding
5", which was the same thing while a session held one corpus and became a trap the
moment it held two: the demo set is exactly five documents, so `existing + 5 > 5` was
true for **any** existing file — one upload permanently blocked the demo corpus, and
with no delete route the only escape was Start over.*

*The limit is now per corpus, and the reasoning it was protecting is unchanged. Five is
a bound on how much a student indexes at once, for cost and for attention; it was never
a claim about a session. The demo set is a **fixture** rather than an upload — nobody
chose those files and their cost is one click — so counting it against a student's own
allowance was conflating two different things.*

**Switch between the demo corpus and your own documents**
- Given both a demo corpus and uploaded documents are indexed, when a student switches
  between them, then only the active one is searched, and a question the other corpus
  answers finds nothing rather than answering from it.
- Given a switch, when the next question is asked, then it is not served from an answer
  cached against the other corpus.
- Given JavaScript is disabled, when the corpus is switched, then it works and the
  choice survives a reload.

**Choose a strategy**
- Given an uploaded document set, when a student selects either strategy and submits a
  question, then the response is generated using only that strategy's pipeline, and the
  trace records which strategy was used.

**Citations on every answer**

*Amended when the web route was added. The criterion previously named "a specific
uploaded document", which a web-grounded answer cannot satisfy — so it enforced the
students-can-tell-the-difference property **structurally**, by making web answers
impossible. Once they are possible that property has to be enforced explicitly, which
is the second criterion below. It is not a weakening: it is the same guarantee moved
from "unreachable by construction" to "asserted by test".*

- Given any generated answer, when it is returned to the student, then it includes at
  least one citation linking back to a specific source — an uploaded document, or a web
  result with its URL — and the citation states which of the two it is; unless no relevant
  content was found, in which case the answer states that explicitly instead of
  fabricating a citation.
- Given an answer citing web results, when it is shown to the student, then its web
  citations are visually distinguishable from document citations, so a student can never
  mistake "my documents said this" for "a search result said this".

**Choose between documents and the web**
- Given the agentic strategy and a configured search provider, when a question is
  submitted, then the router records which source it chose and why, and the trace shows
  the choice alongside the confidence behind it.
- Given no search provider is configured, when the agentic strategy runs, then the web
  source is never offered to the model and no web tool appears in the trace — the router
  cannot select a source that does not exist.
- Given a web search is performed, when the session's search-call allowance is already
  spent, then the call is refused before it is made, and its cost appears in the session
  total rather than as zero.
- Given the agentic strategy routes to the web and the naive strategy cannot, when both
  have run, then the comparison says so explicitly rather than reporting the naive run as
  having simply found less.
- Given a search provider is configured, when a student opens the workspace, then a web
  search toggle is offered and it starts **off** — configuring a provider makes the route
  available, and asking for it is a separate act.
- Given the toggle is off, when the agentic strategy runs and a document search comes up
  empty, then the model is not offered the web tool, no search provider is called, and a
  tool call the model makes anyway is refused and shown as refused.
- Given no search provider is configured, when the workspace is opened, then no toggle is
  shown — a control that cannot enable anything is worse than no control.
- Given the toggle is on, when a document search comes up empty, then the ReAct loop may
  call `search_web`, and it is the only path by which a query reaches the web.
- Given JavaScript is disabled, when the toggle is used, then it works and the choice
  survives a reload.

**Live trace of each step**
- Given a question is submitted, when the pipeline begins processing, then each
  `AgentStep` (route, decompose, retrieve, call_tool, synthesize, as applicable to that
  strategy) streams to the trace view within 2 seconds of that step completing.

**Predicted-outcome question set**

This criterion is the mitigation for the Section 7 risk *"students may conflate 'agentic'
with 'always better' if demo questions aren't chosen deliberately"*, and
it is what Goal 1 — identifying the most cost-effective strategy for a **scenario** —
actually measures. A platform that only ever demonstrates orchestration's cost teaches
"agents are never worth it", which is as wrong as the misconception it replaces.

- Given the demo document set is indexed, when the question set is offered to a student,
  then each question carries a predicted outcome — which strategy should win, or that
  neither should — and that prediction is one the evaluation harness verifies, not one
  asserted only in the UI.
- Given a question predicted to favour the agentic strategy, when the evaluation harness
  runs, then the mechanism that earned it that prediction measurably improves on it over
  asking the question as written; if it stops doing so, the harness fails rather than the
  label quietly becoming false.

  *Amended when the pain-point work landed. This criterion previously named "splitting
  that question", because decomposition was the only mechanism with a ground truth in the
  golden set and "agentic wins" and "splitting helps" were therefore the same claim. They
  are no longer: four mechanisms now carry a prediction, and the summarization question is
  labelled agentic-wins correctly while splitting it changes nothing at all — what answers
  it is reading every chunk. Verifying the wrong mechanism would have forced a choice
  between an unverified label and deleting a question that demonstrates a real pain point.
  The guarantee is unchanged and now says what it always meant.*
- Given the labelled questions are offered, when a student has uploaded no documents,
  then the questions are not presented as runnable — a predicted outcome about a document
  set nobody indexed is not a prediction.
- Given JavaScript is disabled, when a labelled question is chosen, then it still submits
  and runs — consistent with the single-machine criterion below.

**Raw/narrated toggle**
- Given a completed trace, when a student toggles to narrated view for the first time on
  a given step, then a plain-language narration is generated and cached; when toggled
  again for the same step, then the cached narration is shown without a new LLM call.

**Compare mode**

*Two features share this story. `POST /api/v1/compare` runs one question through both
strategies at once — the first criterion below. The Compare **page** is retrospective: it
puts two runs the session has already made side by side. The criteria after the first are
its, and they exist because the page ignored the story's last four words — "on the same
question" — for two milestones. It pinned the most recent run of each strategy, so a
session that had asked them different things was shown a cost ratio between two unrelated
pieces of work, by default, with nothing saying so.*

- Given one question and one document set, when Compare mode is run, then both strategies
  execute and the results table displays latency, token cost, and a quality score for
  each, even if one strategy fails (in which case that strategy's column shows the
  failure, not a blank cell, and the other still renders).
- Given several runs in a session, when the comparison is opened, then which run of each
  strategy it compares is **chosen**, every run of that strategy is offered, and the
  choice survives in the URL.
- Given no choice has been made, when the comparison is opened, then it defaults to the
  most recent question that more than one strategy has answered — not the most recent run
  of each. A comparison that is only valid once the reader repairs it is one that misleads
  every reader who does not.
- Given the two chosen runs asked different questions, when the comparison is shown, then
  it says so, states that the ratios are not a measure of orchestration, and withholds the
  verdict — the one sentence on the page that makes a causal claim.
- Given two chosen runs, when the comparison is shown, then both answers are on it. The
  metrics say what each run cost; only the answers say what it bought, and the verdict is
  explicitly unable to speak for them.

**Watch the pipeline run**

*The platform assumed a great deal of its audience. The canvas drew the four
orchestration stages of a query, because it was built to answer "what does agentic
cost?" — a question that presupposes you already know what retrieval is. Indexing
happened inside one opaque step and was reported as "12 chunks"; retrieval rendered as
"3 passages · best 0.81". A student meeting the subject for the first time saw an
outcome at every stage and a mechanism at none.*

*The stages below are not new work the system does. They are the work it always did,
made visible.*

*The first attempt at this passed every criterion below except the one that was missing.
It drew a rail of stage names and put each stage's data behind a click — technically all
of it on screen, none of it in front of anyone. A class watching from the back of a room
cannot click, and an instructor narrating a run should not have to. Hence the second
criterion, which is the one that would have caught it.*

- Given a document is uploaded, when it is indexed, then each of parse, chunk, embed and
  store appears as its own stage as it happens, and each shows what it actually
  produced — the extracted blocks, the chunk text, the vector, what went into the index.
- Given any stage has run, when the canvas is on screen, then that stage's real data is
  drawn **without a click** — the overlapping chunks, the vector, the scored candidates
  with their threshold — and the flow between stages is drawn as a diagram rather than
  listed, so what is happening is legible from across a room.
- Given several documents are indexed, when a student selects one in the sidebar, then all
  four indexing stages describe *that* document, and the track names it. The default is
  the most recently indexed, which is the one a class just watched.
- Given a selection has been made, when a stage is opened, closed, or a question is asked,
  then the indexing track still describes the selected document — the default is a
  different document, so losing the selection silently changes what the numbers are about.
- Given the four indexing cards are on screen, when any of them has data, then all of them
  belong to one document. Numbers that look like one document's and are several documents'
  are worse than only ever showing the last.
- Given a document failed to index, when it is selected, then the stage it failed at is
  shown and the stages after it are pending — not another document's.
- Given a chunk overlaps the one before it, when that chunk is shown, then the repeated
  text is marked, so the reason for overlap is visible rather than described.
- Given any embedding, when its stage is shown, then the text and the numbers it became
  are shown together, with the width of the vector stated.
- Given a question is asked, when retrieval runs, then every candidate passage is shown
  with its similarity score and the threshold that kept or dropped it — not only the
  ones that survived.
- Given passages have been retrieved, when the prompt is assembled, then the assembled
  prompt is shown in full, because that text is the entirety of what the model sees.
- Given a fresh session, when the page is opened, then no stage claims to have run:
  the canvas starts empty and fills as things happen.
- Given a run has finished, when a student clicks any earlier stage, then that stage
  opens in place with the whole of its data, without re-running anything and without the
  rest of the pipeline leaving the screen.
- Given a question is asked while a previous answer is on the canvas, when the new run is
  in flight, then no answering stage shows the previous run's numbers — a plausible wrong
  figure is worse than an empty one.
- Given a stage is running, when the canvas is on screen, then it is shown as running
  **while it runs**, and shows no data of its own until it has some. A canvas that only
  ever draws finished work shows a jump, not a process — which is what a student who has
  never seen retrieval needs to watch.
- Given some stages complete in a few milliseconds, when an instructor turns on slow
  motion, then the run holds between stages so a room can follow it — and every duration
  and cost on screen remains the measured one, with the canvas stating that it is paced.
  A tool that would let a delay be read as a measurement has no business showing either.
- Given a viewport of at least 900px, when any view is open, then the page does not
  scroll: a class watches this together and a room cannot scroll.
- Given JavaScript is disabled, when a document is indexed or a question asked, then
  every stage is still reachable and still shows the same data.

**Read any run**

*The raw trace showed the last run and nothing else. Everything earlier in the session —
each document's indexing, every previous question, any summary — was in the store and
unreachable, so the page could answer "what did that just do?" and not "what did it do
differently last time?". The second question is the comparison this platform exists to
teach, and it is the only reason to keep a raw trace at all.*

- Given several runs in a session, when the trace page is opened, then every one of them
  is listed — indexing included, because what a document cost to index is half of what
  the platform measures — newest first, each naming what it was.
- Given a run in that list, when it is selected, then every step of *that* run is shown
  in full and no step of any other.
- Given a run in that list, when its cost is shown, then it is the cost of the run's
  top-level steps: a parent aggregates its children's usage, so a naive sum would report
  double every LLM call, and the figure must agree with the answer and the comparison
  table for the same run.
- Given a link to a run that is not in this session, when it is opened, then the most
  recent run is shown instead — a stale link is the only way to hold one, and being
  correct about the missing run helps nobody.
- Given JavaScript is disabled, when any run in the list is selected, then it opens.

**Summarizer mode**

*Promoted from should-have when it was built. Its teaching job is a **contrast**, not a
comparison: summarization reads everything and its cost scales with the corpus, where
retrieval reads the relevant part and its cost scales with the question. It is
deliberately not a third strategy — it does not retrieve at all, so putting it in the
`Strategy` enum would make Compare mode's one variable stop meaning orchestration.*

*It is its own page beside Run, Compare and Trace, not a button in the rail. It was the
latter, and that put the most expensive action Axis offers one click away with no choice
of documents and no confirmation; its result was also reachable only by pressing that
button again, so a student who opened the trace to see the map-reduce steps lost the
summary they went there to explain. Choosing documents is what makes the cost curve
watchable rather than asserted: summarize one document, then four.*

- Given at least one indexed document, when a student asks for a summary without having
  asked any question, then a structured overview is produced, and each section cites the
  document and location it came from.
- Given several indexed documents, when a student selects a subset and summarizes, then
  only those documents are read, and the overview reports how many it covered and what
  it cost.
- Given no document is selected, when the student submits, then it is refused before any
  LLM call is made — an empty selection is a request for nothing, and reading it as a
  request for everything would make the most expensive action the outcome of a mistake.
- Given a document failed to index, when the student opens the summarize page, then it is
  listed and cannot be selected, rather than being hidden.
- Given a summary has been produced, when the student navigates away and back, then it is
  still on screen and no further LLM call was made.
- Given a summary is requested, when the session's cost cap is already reached, then it
  is refused before any LLM call is made — summarization reads the whole corpus and is
  the most expensive thing a student can run after Compare.
- Given no documents are indexed, when a summary is requested, then it says so rather
  than returning an empty overview.
- Given a summary has been produced, when the student looks at the trace, then the
  per-document and combining steps appear separately, so the map-reduce shape and where
  its cost went are both visible.

**The four ways naive RAG fails**

*This is the criterion the whole platform was missing, and the reason is worth stating.
Axis could always show what orchestration **costs**. What it could not show was the
shape of the problem orchestration exists to solve — so a student learned a price
without learning what they were buying. The course material students meet first
(`reference/module_3_Enterprise RAG/learning-materials/reference/enterprise-rag.md`)
names four specific failures of naive retrieval and then hands the answer forward as an
open question. Those four are the syllabus; this criterion makes each one a run.*

*Each of the four is answered by a **different** mechanism, and that is the lesson. A
student who leaves believing "agentic is better" has learned less than one who leaves
knowing that a comparison needs decomposition, an inferential question needs a second
retrieval informed by the first, an overview needs to read everything, and a follow-up
needs its references resolved.*

- Given the demo corpus is indexed, when a student opens the pain-point page, then each
  of the four failures is named in the same words the course material uses, beside the
  mechanism that answers it and a question that exhibits it.

  *"Opens the page" is read as the state before anything is clicked, and the page is
  built to make that state the honest one: nothing is expanded on load, so all four cards
  carry all three of these. Once a card is opened the other three narrow to about a
  quarter of that width and give up their mechanism and question, keeping their heading
  and the symptom — which this criterion permits and the geometry requires. Pinned by
  `test_all_four_failures_are_on_screen_without_being_clicked`, whose assertions are
  unchanged across two redesigns of that row.*
- Given a pain point is chosen, when the student runs it, then the same question runs
  through the baseline and the agentic strategy, both answers are shown, and the measured
  quantity that distinguishes them is shown with them — not a claim that one is better.
- Given a pain point's prediction is shown, when the evaluation harness runs, then that
  prediction is one the harness verifies against the golden set; if it stops holding, the
  harness fails rather than the page quietly promising an outcome nothing measured.

  *"Verifies" means a **recorded** measurement matching the running configuration, and the
  amendment is there because the original reading was not enough. The harness printed its
  verdict to a terminal and persisted nothing, so when two ceilings stopped paying off the
  build went red and the page did not change a word — it went on stating figures the
  harness had just contradicted. A card now reads `ceilings.json` and claims a measurement
  only when one exists for this embedding model, these retrieval settings and this corpus;
  otherwise it says so. "The harness fails" was true and insufficient: the failure has to
  reach the student, not only the person who ran it.*
- Given the student's own documents are the active corpus, when a pain point is opened,
  then the symptom and the mechanism are unchanged and the student supplies the
  question — and the card states plainly that nothing measured this one, so the shape is
  demonstrated and the figure is not.

  *The amendment that needed the most care, because it is the first time this page shows
  a run it cannot verify. The rule it must not break: **every claim is verified or is
  visibly marked as not verified, and there is no third state.** A card that quietly
  dropped its measured line when the corpus changed would leave a student reading the
  same layout and assuming the same rigour.*

  *Allowed at all because the alternative is worse. The demonstrations are claims about
  five specific documents, so on anyone else's material the page went dead exactly where
  a student most wants to try the idea — and "recognise which of the four shapes a given
  bad answer is" is an exercise the course material already sets
  (`learning-materials/study-material/exercises.md`, exercise 3). What is lost is the
  number. What is kept is the comparison, both answers, and the honest report of whether
  the mechanism actually fired — which on a self-chosen question does more work, since a
  question that is not really a comparison will be reported as one the decomposer did
  not split.*
- Given a question that needs two lookups chained — the second knowable only from what
  the first returned — when the agentic strategy runs, then the trace shows a second
  retrieval whose query the model wrote from the first one's result, and the baseline's
  trace shows one retrieval.
- Given a question asking for an overview of the corpus, when both are run, then the
  number of chunks each path actually read is reported, because "retrieval returns
  chunks, not the whole picture" is a claim about coverage and coverage is countable.
- Given no documents are indexed, when the pain-point page is opened, then its runs are
  not offered — a demonstration about a corpus nobody indexed demonstrates nothing.
- Given JavaScript is disabled, when a pain point is run, then it still runs and renders.

**Conversational memory**

*Deliberately narrow, and the narrowness is the teaching point. Axis's memory resolves
**references**; it does not carry **facts**. The course material's own example — "Alice
has a parrot", then "Bob has two cats", then "how many pets?" — asks the model to answer
from the conversation, and Axis will not do that: a fact recalled from chat history has
no passage to cite, and Section 6's citation criterion forbids exactly that answer. So
the follow-up is resolved into a standalone question and then retrieved for, which is
grounded, and the difference is worth a minute of class.*

- Given a question has been answered, when a follow-up referring to it is asked of the
  agentic strategy, then the follow-up is resolved into a standalone question before
  retrieval, and both the question as typed and the question as resolved are shown.
- Given the same follow-up is asked of the baseline, when it runs, then it is retrieved
  for as typed and the conversation is not consulted — the baseline has no memory, and a
  baseline with one is not a baseline.
- Given a resolved follow-up, when its answer is returned, then every claim in it is
  still cited to a passage; nothing is answered from the conversation itself.
- Given a student starts a new conversation, when they do so, then the turns are
  forgotten and the indexed documents are not — the two are different things to discard.

**Semantic cache**

- Given a question has been answered, when a reworded question with the same meaning is
  asked, then the stored answer is returned, nothing is retrieved, no answer is
  generated, and the page shows the question it matched and how close the match was.

  *Amended during implementation, and the amendment is a real cost worth stating rather
  than hiding. The criterion first said "no LLM call is made", which holds on the first
  turn of a conversation and not afterwards: once there is history, the question has to
  be **resolved before it can be looked up**, because "how long is it?" keyed on its own
  four words would match a previous "how long is it?" about something else entirely and
  serve the wrong answer with citations and a straight face. So a hit inside a
  conversation costs one resolution call — one instead of four, and no retrieval — and a
  hit outside one costs none. Keying on the raw question always, as the reference
  implementation does, would have satisfied the original wording by being wrong.*
- Given a cache hit, when the answer is shown, then it carries the citations it was
  originally produced with — a cached answer with no provenance is worse than a slow one.
- Given a question whose answer depends on when it is asked, when it is submitted, then
  the cache is bypassed in both directions, because a cache with no staleness policy
  answers a question about today with an answer about last week.
- Given a new document is indexed, when a previously cached question is asked again, then
  it is not served from the cache — the corpus it was computed against no longer exists.
- Given a run that was answered from the cache, when it appears in the comparison, then
  the comparison states that and withholds its cost ratio, because the ratio would read
  as orchestration being free.
- Given the cache is turned off, when the same question is asked twice, then it is
  answered twice at full price — an instructor needs to be able to show the bill.

**Per-session cost/rate caps**
- Given a session has reached its configured cost or request cap, when a new query is
  submitted, then it is rejected with a clear message stating the cap was reached, before
  any LLM call is made.

**Single-machine reliability**
- Given a fresh machine with only API keys configured, when Axis is started, then all
  three layers (Frontend, Backend, AI Backend) come up and pass the `/api/v1/health`
  check without any external service beyond the configured LLM/embedding/search providers.

**A shared password in front of a hosted deployment**
- Given a deployment with a password configured, when any path is requested without a
  valid access cookie — a page, `/api/v1/*`, or a static asset — then a screen asking
  for the password is returned and the application is not reached.
- Given the correct password is submitted, when the screen is posted, then a signed
  cookie is set that does not contain the password itself, and the application is
  reached on the next request.
- Given no password is configured, when Axis is started, then nothing is in the way —
  the local `python -m axis` path is unchanged, and a deployment that lost the setting
  fails open rather than locking an instructor out in front of a class.

*Added when Axis was first hosted. It is a property of a deployment rather than of the
product: the single-machine story above describes a laptop in a room, where the door is
the room. A URL has no door, and the API keys behind it are the instructor's.*

*Vercel's own password protection would have been the right place for it and is behind
an add-on this account does not have — the API answers `428
invalid_password_protection`. Its other built-in, Vercel Authentication, requires each
visitor to hold an account with access to the team, which a class does not. So the gate
is Axis's own, and it deliberately follows the one Module 3's Alex already uses.*

**Reporting an answer as wrong**
- Given a rendered answer, when a student looks at the bottom of it, then there is a
  closed disclosure offering to report it, and opening it offers a fixed set of reasons
  that name what is wrong rather than a free-text box alone.
- Given a report is submitted, when it is recorded, then it carries the `trace_id` of
  the run that produced the answer, so the run can be reopened at `/trace?id=…` and read
  stage by stage.
- Given a reason outside the offered set is posted, when it is recorded, then it is
  stored as unspecified rather than echoed, and a free-text note is collapsed to one
  bounded line so it cannot forge or bury the entries around it.

*The sink is a structured log line, which is a floor rather than a finished feature and
is recorded as such. The session store is `:memory:` on the hosted deployment and is
erased with the instance, so a table of reports would quietly lose them; a durable sink
is a database-shaped decision this does not pre-empt.*

---

## 7. Risks & Assumptions

| Risks | Assumptions |
|---|---|
| A ceiling measured under one embedding model does not hold under another, so a figure shown on the *Why agentic* page can silently stop being true when the provider changes | Students will have reliable, if shared, network access to the configured LLM providers during class |
| LLM-as-judge quality scoring may be inconsistent or biased toward verbose answers | The instructor will supply or pre-approve API keys and a budget ceiling for each workshop session |
| Comparison-mode cost adds up quickly across a full workshop's worth of students running Compare repeatedly | A golden Q&A evaluation set can be authored by the instructor/TAs before the first cohort, covering both strategies |
| Provider API rate limits could throttle an entire classroom hitting the same provider simultaneously | A single laptop/workstation has enough RAM/CPU to run Chroma and the FastAPI app simultaneously without degraded performance |
| Non-deterministic LLM outputs mean the same question may produce a different trace on each run, complicating live explanation | Class size is small enough (assumed well under a few dozen concurrent sessions) that per-session caps are sufficient without a request queue |
| Students may conflate "agentic" with "always better" if demo questions aren't chosen deliberately | The instructor will select or approve the specific documents and demo questions used in class ahead of time |
| A web-routed answer could be mistaken for one grounded in the student's own documents, teaching them to trust a citation they cannot check | Web search snippets are advertising-funded search results, not vetted sources; the platform's job is to make their provenance obvious, not to assess their quality |
| Students may conclude "agentic = has web access" rather than "agentic reasons about retrieval", if the web route becomes the only way the agentic strategy ever wins | The labelled question set keeps at least one documents-only question on which decomposition alone beats a single blended retrieval (Section 6, predicted outcomes) |

---

## 8. Open Questions

- What is the actual per-student API budget for a workshop session, and does it match
  the $2 target in Section 2? — *Owner: Instructor / program budget owner*
- ~~Should the Backend and AI Backend run as two separate services from day one, or stay
  one process for now (see System Design, Section 6.2)?~~ — **Resolved (Milestone -1,
  Engineering):** one process for all three layers. Backend ↔ AI Backend is an in-process
  Python call across an interface boundary; Frontend ↔ Backend are two distinct ASGI apps
  mounted in that same uvicorn process, talking over localhost HTTP so the REST/SSE
  contract stays real. Rationale and the trade-off against a distributed deployment are
  recorded in System Design Section 6.2.
- Which LLM/embedding/search providers will actually be available during the live class
  (API keys, rate limits, regional restrictions)? — *Owner: Instructor*. **Still open, and
  it does not block the build.** The *search* half is now a decision rather than a scope
  gap — see the resolved entry below. The *LLM* half constrains
  one thing: an agentic strategy needs a provider that can call tools, so Ollama is not a
  valid configuration for Milestones 1 and 3 (Axis refuses to start rather than running a
  silently non-agentic loop — System Design Section 10).
- Will students code alongside the instructor on their own machines, or only observe a
  single live demo? This changes whether concurrent multi-session load needs to be
  handled for a full classroom. — *Owner: Instructor*
- What size and composition should the golden Q&A evaluation set have to fairly test both
  strategies, including enough compound and multi-hop questions that the agentic win is
  measured rather than assumed? —
  *Owner: Instructor / TAs*. **Still open.** A starter set of 15 questions over synthetic
  fixture documents ships with Milestone 0 (`ai_backend/evaluation/golden/`) so the
  milestone gate is unblocked; it covers text, table, image, lexical, relational, and
  four deliberately unanswerable questions. It is built to be replaced wholesale — the
  YAML schema is the contract, not the content.
- Are the pre-workshop baseline figures in Section 2 (30% correct-strategy identification,
  ~0% trade-off recall) backed by actual data from a prior cohort, or are they estimates
  that need validation? — *Owner: Instructor*
- ~~Should the agent be given web search, given that the citation criterion names "a
  specific uploaded document"?~~ — **Resolved (Product):** yes. The reference notebook
  defines agency as *source selection*, and a router with one source to select from
  demonstrates the concept in name only — a student sees a `route` step whose decision is
  never "somewhere else". The web route makes the routing decision real and contestable,
  which is what Goal 5 (naming a trade-off per strategy) actually requires.

  What it cost, recorded so the trade is auditable rather than implied:

  - **Section 6's citation criterion is amended**, and the property it enforced by
    construction — a student can always tell whether an answer came from their own
    material — is now an explicit criterion asserted by test.
  - **Web snippets are untrusted third-party text entering prompts and the trace.** That
    is a prompt-injection surface uploaded documents only weakly had. It is bounded
    (snippets are labelled untrusted in the synthesis prompt, the grounding rules are
    unchanged) and **not eliminated**; System Design Section 6.5 records it as accepted,
    and it is itself worth a few minutes of class.
  - **Search is billed per call, not per token**, so it needed its own counter and cap
    rather than riding on the token estimate.
  - **A live demo must not depend on the network** (Section 5, single-machine). Hence a
    `cached` provider alongside the live one: the reference notebook's own internet cells
    show a 404 in their committed output, which is exactly the failure this avoids in
    front of a class.

  Naive RAG is deliberately **not** given web access. It is the baseline, and a baseline
  with fewer sources than the thing it is measuring is not a baseline.

---

## 9. Success Metrics

**Leading indicators** (early signals, visible during development and dry runs):
- Percentage of milestone builds (PRD milestones — see System Design, Section 12) that
  pass their evaluation slice on the first run
- Median Compare-mode latency observed during internal dev/QA testing, tracked against
  the 45-second target in Goal 2
- Number of trace steps that fail to render or narrate correctly during QA passes
- Per-session cost observed during dry-run sessions, tracked against the $2 target in Goal 3

**Lagging indicators** (final outcomes, measured after live class delivery):
- Post-class quiz score on strategy identification (ties to Goal 1)
- Post-class survey: percentage of students who can name a trade-off per strategy
  unprompted (ties to Goal 5)
- Actual per-student cost incurred during the live workshop vs. the $2 budget target
  (ties to Goal 3)
- Count of unrecoverable failures during actual class delivery (ties to Goal 4)
- Student satisfaction/NPS specifically for the hands-on lab portion of the class
