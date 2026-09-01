# Module 3: Exercises

No coding required for any of these. They use ChunkViz, a real (or invented but realistic) internal document, and the pain-point examples from the lesson, no built app is required to do them.

## Exercise 1: See chunk size and overlap for yourself

**Goal:** Build direct intuition for why chunk size and overlap matter, instead of taking it on faith.

**Steps:**
1. Search for "ChunkViz" (the tool shown in class) and open it. Paste in a few paragraphs of real text, an email you've sent, a section of a document, or the sample Nelson Mandela paragraph from `reference/chunking-strategies.md`.
2. Set chunk size to something small (e.g. 50 characters) and note how many chunks you get, and how many chunk boundaries land in the middle of a sentence.
3. Increase chunk size until sentence boundaries are respected, and separately, increase chunk overlap from 0 to a meaningful amount (e.g. 10-20% of chunk size), and describe what changes about the highlighted overlap regions.

**Done when:** You can point to one concrete example, in your own pasted text, of a chunk boundary that split a sentence badly, and explain in one sentence why that specific chunk would retrieve poorly for a question about that sentence.

## Exercise 2: Match the source to the chunking strategy

**Goal:** Practice picking the right chunking strategy for a given kind of document, the actual decision you'd make before building any ingestion pipeline.

**Steps:**
1. For each of the following four sources, pick one of the five chunking strategies from the lesson (Fixed-Size, Recursive, Document-Based, Semantic, Agentic): (a) a 100-page HR policy manual with consistent H1/H2 Markdown headings, (b) a folder of raw, unstructured customer support chat transcripts, (c) a single dense legal contract with numbered clauses but no headings, (d) a set of highly technical incident post-mortems where topic boundaries don't line up with paragraph breaks.
2. For each choice, write one sentence naming the specific structural feature (or lack of one) in that source that drove your pick.
3. For source (b), specifically explain why Document-Based Chunking would underperform there, even though it's the cheapest structure-aware option.

**Done when:** You have four strategy picks, each with a one-line justification naming the actual structural feature, not just "this one seemed right."

## Exercise 3: Diagnose the naive RAG failure

**Goal:** Practice recognizing which of naive RAG's four specific failure shapes (summarization, comparison, multi-hop, memory) a given bad answer actually is, since the fix is different for each.

**Steps:**
1. For each scenario below, name which of the four specific failure shapes it is, and justify it in one sentence:
   - A user asks a RAG system to "summarize our Q3 security incidents," and gets back a summary that only mentions one incident, even though four are documented in four different chunks.
   - A user asks "which of our two vendors, Acme or Globex, has the better SLA," and gets a confused answer that mostly discusses Acme and never directly states which is better.
   - A user says "the deploy window is Tuesdays," then two messages later asks "when can I deploy this," and the system asks the user to restate the deploy window because it has no idea it was already told.
2. For each, name the single Enterprise RAG stage (from `reference/enterprise-rag.md`) that most directly fixes it.

**Done when:** All three scenarios are labeled with the correct failure shape and the correct fixing stage, and you can explain why the same fix (e.g. "just retrieve more chunks") would not have solved all three.

## Exercise 4: Design an Enterprise RAG router for your own organization

**Goal:** Apply the Enterprise RAG architecture to a knowledge base you actually understand, your own team's or organization's data, instead of the generic Financial/Technical/HR example from the lesson.

**Steps:**
1. List three to five distinct knowledge bases that exist (or should exist) in your own organization, e.g. "customer contracts," "engineering runbooks," "internal wiki," "HR policies."
2. For one specific, sensitive query a user might ask (e.g. one that should only be answerable by certain roles), describe what the Agentic Router should do: which knowledge base(s) should it route to, and what access-control check should happen before retrieval, not just before display.
3. Name one query that would benefit from the Semantic Cache specifically, i.e. a question you'd expect many different users to ask in slightly different words.

**Done when:** You have a short routing table (knowledge base -> who can query it) and one concrete example each for the router and the semantic cache, grounded in your own organization rather than the lesson's generic example.

## Exercise 5: Trace one query through the full pipeline

**Goal:** Hand-trace a single query through all three RAG stages plus the Enterprise RAG stages wrapped around them, tying Concepts 5 through 8 together end to end.

**Steps:**
1. Pick one real question you might ask an internal knowledge base at your organization.
2. Write out, stage by stage: what gets embedded at ingestion time (which documents, chunked how), what happens when your query is embedded and searched, and what the final assembled prompt to the LLM would roughly contain.
3. Now add the Enterprise RAG stages: would your query hit the semantic cache on a repeat ask? Does it need the query rewriter (is it a comparison, or does it depend on prior conversation)? Which knowledge base would the router send it to, and would access control block anything?

**Done when:** You can point to a specific chunk (or a description of one) that would need to be retrieved for your query to be answered correctly, and you've named at least one Enterprise RAG stage that would meaningfully change how naive RAG would have answered the same query.
