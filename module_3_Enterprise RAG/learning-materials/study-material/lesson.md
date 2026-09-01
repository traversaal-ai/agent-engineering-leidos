# Module 3: Enterprise RAG (Retrieval Augmented Generation)

## Learning objectives

By the end of this module you can:

- Explain why LLMs need RAG at all: the context window limit and the "LLMs don't know your data" problem
- Describe the three stages of any RAG pipeline: Ingestion, Retrieval, Generation
- Explain what an embedding and a vector database are, and how vector search differs from keyword search
- Name the five chunking strategies and pick the right one for a given source document
- List naive RAG's specific pain points: irrelevant retrieval, poor summarization, weak comparison, no multi-hop reasoning, no memory, no permissions
- Describe the Enterprise RAG architecture and which stage fixes which naive-RAG pain point

Agentic RAG (routing, one-shot query planning, tool use, conversation memory), multi-agent systems, and RAG evaluation are next class's material, not covered here.

## Prerequisites

You've completed Module 1 & 2 (Intro to Agents; Skills, CLAUDE.md & Agent Operating System) and are comfortable with the agent harness, the agent loop, and the three levels of agent sophistication (automation, ReAct, multi-agent). This module builds directly on that foundation, applied to one specific tool an agent can use: retrieval.

---

## Concept 1: Why can't you just paste your documents into the prompt?

Enterprise data for most organizations is fragmented across dozens of applications, most departments use between 40 and 60 different tools (Slack, Salesforce, Gmail, Dropbox, GitHub, and more), each holding its own slice of the organization's knowledge. Finding a simple answer across that sprawl requires tons of time and effort: data analysts spend roughly 80% of their time just *preparing* data to answer business questions, before they ever get to answering the question itself.

The deeper reason this is hard: **LLMs don't know your data.** ChatGPT or Claude was trained on the internet. It has no idea what's in your company's docs, your codebase, or last week's report, because those are internal to your organization. Asked about them anyway, the model might hallucinate, confidently generating something false because it has no real grounding to draw on. The meme version of the distinction: without RAG, an LLM is a "know-it-all" (guessing); with RAG, it's "knows-enough" (grounded in facts it actually retrieved).

Even setting hallucination aside, two hard limits stand in the way of just pasting documents in:

1. **The context window.** An LLM's context window is the fixed number of tokens (to the left and right of wherever it currently is) it can attend to. A blog post is ~1,000 tokens; a novel is ~128,000; an encyclopedia is ~2,000,000. Whatever falls outside the window, whether it's user input or the model's own output pushing older content out, is simply ignored, not remembered, not used. You cannot paste a whole document library into a single prompt and expect the model to use all of it.
2. **Cost and latency.** Even for the content that *does* fit, every input and output token has a price (e.g. Gemini 2.0 Flash: $0.10 per million input tokens; more capable models cost more) and adds response time. Sending an entire document on every single query, most of which is irrelevant to that specific question, wastes tokens, money, and time on every call.

**Check:** If an LLM's context window is 128,000 tokens and your combined "user input + retrieved context + expected output" for one query is 200,000 tokens, what specifically happens to the excess, and is it the beginning or the end of that combined content that gets cut?

---

## Concept 2: The solution, store knowledge where you can retrieve it instantly

**Enterprise Knowledge Management (EKM)** is the systematic process by which organizations capture, store, manage, and share their collective knowledge. The technical mechanism that makes EKM queryable by an LLM is what we've been calling **Retrieval Augmented Generation (RAG)**.

The core idea, at a glance:

```
Corpus (your documents) -> Embedding Model -> Vector Store  <- Embedding Model <- Query
                                                    |
                                          Retrieved Documents
                                                    |
                                                    v
                                          Generative Model -> Response
```

Instead of trying to fit everything into the prompt, you store your knowledge somewhere it can be *searched*, retrieve only the pieces relevant to a given question, and hand just those pieces to the LLM. This is exactly the pattern you already see in modern AI products: when a tool offers "Add photos & files," "Web search," or a connected GitHub/Canva integration, it is retrieving from a source and augmenting the model's context with it, the same core mechanic, just wired up to different data sources.

**Check:** In your own words, what does the "Augmented" in Retrieval-Augmented Generation actually refer to? What specifically gets augmented, and with what?

---

## Concept 3: Embeddings, turning meaning into numbers

An **embedding** is the numerical representation of a piece of data, text, an image, or audio, as a vector (a list of numbers). A tiny 4-dimensional example:

```
cat  => [1.2, -0.1,  4.3,  3.2]
mat  => [0.4,  2.5, -0.9,  0.5]
on   => [2.1,  0.3,  0.1,  0.4]
```

Real embedding models use hundreds or thousands of dimensions, but the principle holds: an embedding model converts documents, images, or audio into vectors, and all of those vectors share one space, where **geometric closeness stands in for semantic closeness**. That's why vector search returns similar items based on their semantic meaning rather than exact term matches, a search for "kitten" can land near "cat" and "dog" in that space, without the word "cat" ever appearing in the query.

**Check:** Why would a keyword search for "kitten" fail to return a document about "cats," while a vector search for the same query succeeds?

---

## Concept 4: Vector databases, finding what's similar, fast

A **vector database** stores millions of embeddings and finds the most similar ones in milliseconds, by meaning, not keywords:

```
Your question -> [0.81, 0.15, 0.65]  -> similarity search -> Vector DB -> Top 3 matching chunks returned
```

Under the hood there are two parallel paths: a **write path** (embed the data, pair it with metadata, index it, e.g. into an HNSW graph) and a **query path** (embed the query, compare it against the index using a metric like cosine similarity, return the top-K nearest neighbors). Common tools: Pinecone, Weaviate, Qdrant, pgvector.

A vector database is not a replacement for a relational database, they solve different problems and are usually used together. A relational database (PostgreSQL, MySQL) is the **system of record**: rows, columns, foreign-key relationships, ACID transactions, found via exact-match SQL queries. A vector database is the **semantic retrieval layer** built on top: high-dimensional embeddings, found via approximate nearest-neighbor search. The typical enterprise flow: relational DB (system of record) -> embedding pipeline -> vector DB (semantic retrieval layer) -> RAG query flow.

**Check:** You need to find "every invoice for customer #4521" (an exact match) versus "documents that discuss customer complaints about billing" (a semantic match). Which database is right for each, and why would using the wrong one for either query be a bad idea?

---

## Concept 5: The three stages of RAG

Every RAG system, however simple or sophisticated, breaks into the same three stages.

**Stage 1: Ingestion**, turn raw data into searchable knowledge.
```
Data Sources -> Load & Extract -> Chunk -> Embed -> Store
(docs, web pages,   (parsers, OCR)   (chunking     (embedding    (vector DB)
 databases, APIs)                     strategy)     model)
```
Goal: make your data machine-readable and semantically searchable, so it can be used by LLMs to generate accurate, grounded answers.

**Stage 2: Retrieval**, turning a question into a search.
```
User Query -> Embed Query -> Search Vector DB -> Retrieve Relevant Chunks (with similarity scores)
```
Goal: retrieve the most relevant and useful context from your data to ground the model's response. The query must be embedded with the *same* model used at ingestion time, otherwise the query vector won't land near the right stored chunks.

**Stage 3: Generation**, augment and answer.
```
Retrieved Chunks -> Build Prompt (system + query + context) -> Generate Answer -> Post-process (verify, guardrails, citations) -> Final Answer
```
Goal: generate accurate, trustworthy, well-cited answers grounded in your data.

Put together, this is the full pipeline: an offline **indexing** path (documents -> chunks -> embeddings -> vector database) feeding an online **query** path (user -> query -> embedding -> search -> retrieved context -> augmented prompt -> LLM -> response).

**Check:** Name the one stage where, if it's done badly, no amount of a smarter LLM at generation time can fix the resulting answer. Why is that stage the bottleneck?

---

## Concept 6: Chunking, and why chunk size matters

**Chunking** is step 3 of Ingestion: breaking your data into smaller pieces before embedding and storing it, because LLMs (and embedding models) have a limited context window and cannot take in your entire dataset at once. Why it matters, specifically: **improved retrieval efficiency** (smaller, focused chunks are faster and cheaper to search), **enhanced accuracy and relevance** (a chunk about one idea matches queries about that idea far better than a chunk blending five ideas), **scalability** (uniform chunks are easier to index and manage as a corpus grows), and **balanced information distribution** (no single chunk dominates every search, or carries no signal at all).

A tool called **ChunkViz** makes this tangible: paste text in, set a chunk size and overlap, and it highlights each resulting chunk in a different color. **Chunk overlap** is a deliberate duplication of a few sentences at chunk boundaries so context isn't lost at the cut. The one thing to watch for and avoid entirely: a chunk boundary landing in the *middle of a sentence*, a clear sign the splitter isn't respecting the actual structure of the text.

### Five chunking strategies

| Strategy | What it means |
|---|---|
| **Fixed-Size** | Split into chunks of a specified character count, regardless of content. |
| **Recursive** | Recursively split using a prioritized list of separators (paragraph, sentence, word) until each chunk fits the target size. |
| **Document-Based** | Split according to the document's own structure: headings, sections. |
| **Semantic** | Divide into chunks that are semantically complete, using an embedding model to find where meaning shifts. |
| **Agentic** | Use an LLM to decide how much and what to include in each chunk, based on context. |

**Worked example, Recursive Chunking.** Input: *"AI is amazing. It is used in medicine, finance, and art. However, it also raises ethical concerns."* (108 characters). Rule: max 50 characters, separators in priority order `[".", ",", " "]`. The text is too long, so it's split on `". "` first, producing three chunks (15, 43, and 49 characters), all already under the 50-character limit, so no further recursion is needed. If any piece were still too long, *that specific chunk* (not the whole document) would be recursively re-split using the next separator in priority.

**Worked example, Document-Based Chunking.** A Markdown document with four `##` headers (Introduction, Applications, Challenges, Conclusion) is split into exactly four chunks, one per section, using the document's own header structure rather than any character-count rule at all.

**Check:** For a legal contract with numbered clauses and a raw customer-support chat log with no structure at all, which of the five strategies fits each source, and why would document-based chunking underperform on the chat log specifically?

---

## Concept 7: Naive RAG and its pain points

**Naive RAG** is the pipeline from Concept 5 with nothing else added: embed the query, retrieve the top-K chunks by similarity, hand them to the LLM, generate an answer. It works, and it breaks down in specific, predictable ways once you put it in front of real enterprise questions.

**General pain points**, for a query like "What are the security best practices?": **irrelevant retrieval** (chunks that just scored in the top K, like "company history," ride along with genuinely relevant ones); **no context awareness** (each chunk is scored independently, with no sense of which chunks belong together); **information overload** (too much unnecessary content reaches the LLM); **confusing answers** (the LLM, confused by the noise, produces off-topic, incomplete, or hallucinated output); **poor efficiency** (higher token usage, slower responses, higher cost, for chunks the answer never needed).

**Four specific failure shapes**, each needs a different fix:

1. **Struggles to summarize.** A document split into four chunks, asked "Summarize what X does," only retrieves the one chunk that scored highest, missing the other three chunks that held the rest of the actual summary. Accurate as far as it goes; incomplete because whole sections were never retrieved.
2. **Comparison is a headache.** "Compare A's and B's leave policy, and tell me which is more generous" gets embedded as *one* blended vector and searched *once*, skewing toward one side of the comparison. What should happen: break the query into sub-questions, retrieve for each separately, *then* compare, naive RAG has no mechanism to do that breakdown on its own.
3. **Implicit data, beyond the obvious.** "Find the author of document X, then find their other publications, then summarize the common themes" needs **multi-hop reasoning**, chaining retrievals together. Naive RAG retrieves once, answers from that single retrieval, and stops; it has no way to chain a second retrieval off the first one's result.
4. **No memory, disconnected dialogue.** Told "Alice has a parrot" and then "Bob has two cats" across two turns, and then asked "How many pets do Alice and Bob have?", a memory-less system can't answer, it has no record either fact was ever stated. Every query is a fresh, standalone retrieval.

There's also a sharper structural gap: naive RAG has **no permissions model**. A vector database with no access control returns whatever is semantically closest, regardless of who's asking. A summer intern asking about a board meeting can retrieve confidential financial detail purely because it was the closest semantic match, naive RAG has nothing that's even aware this shouldn't reach this user.

**Check:** Of the four specific pain points above, which one would adding *more* chunks to the top-K retrieval actually make worse, not better, and why?

---

## Concept 8: Enterprise RAG, fixing naive RAG's pain points with purpose-built stages

**Enterprise RAG** wraps the naive pipeline with stages inserted specifically to address the pain points above:

```
User Query -> Input Guardrail -> Semantic Cache -> Query Rewriter -> Agentic Router -> LLM Generation -> Output Guardrail -> Final Answer
                                        ^                                  |    ^            |
                                   Memory (Context & History)       Access Control    Citation & Provenance
                                                                            |
                                                          KB: Financial | KB: Technical Docs | KB: HR Policies

                              (Monitoring & Observability, with Feedback Loops, wraps the entire pipeline)
```

| Stage | Fixes |
|---|---|
| **Semantic Cache** | Poor efficiency, reuses answers for semantically duplicate queries instead of re-running retrieval and generation. |
| **Query Rewriter** | Comparison headaches (decomposes into sub-questions), and feeds in conversation memory. |
| **Memory (Context & History)** | No memory, disconnected dialogue. |
| **Agentic Router + Access Control** | No context awareness, irrelevant retrieval, *and* the permissions gap, routing to the right knowledge base and enforcing who's allowed to see what, before retrieval happens. |
| **Citation & Provenance** | Trustworthiness, lets a human verify a claim against its actual source. |
| **Input/Output Guardrails** | General safety and policy compliance on the way in and the way out. |
| **Monitoring, Feedback Loops** | Ongoing quality, catching new failure modes after launch, not just at design time. |

Benefits, in short: improved accuracy and relevance, optimized retrieval (hybrid search, dynamic embeddings), enhanced query handling, efficient handling of large datasets through better indexing, and refined initial results through reranking and context compression.

**Check:** Match each of Concept 7's four specific pain points (summarization, comparison, multi-hop, memory) to the single Enterprise RAG stage most directly responsible for fixing it. Is there one pain point this architecture only partially fixes, one where the router picking a knowledge base once up front isn't enough, and you'd really want an agent actively deciding to retrieve *again* based on what it just found? Hold onto that question, it's exactly where next class's material on Agentic RAG and multi-agent systems picks up.

---

## Summary

1. LLMs don't know your data, and their context window and per-token cost mean you can't just paste everything in. RAG retrieves only what's relevant and augments the prompt with it.
2. Embeddings turn data into vectors where semantic closeness is geometric closeness; vector databases search that space by meaning, in milliseconds, and complement (not replace) relational databases.
3. Every RAG pipeline has three stages: Ingestion (parse, chunk, embed, store), Retrieval (embed the query, search, retrieve), Generation (build a prompt, generate, post-process).
4. Chunking is the ingestion step that determines retrieval quality most directly. Five strategies, fixed-size, recursive, document-based, semantic, agentic, trade off cost against how well they respect the source's actual structure and meaning.
5. Naive RAG (retrieve top-K, generate) breaks down on summarization, comparison, multi-hop questions, memory, and permissions, each for a distinct, identifiable reason.
6. Enterprise RAG adds purpose-built stages, semantic cache, query rewriter, memory, agentic router with access control, citations, guardrails, monitoring, each aimed at a specific naive-RAG pain point.

## Where to next

Do `exercises.md` for hands-on practice with chunking and pain-point diagnosis. Or ask to be quizzed (`quiz.md`). Next class covers **Agentic RAG and Multi-Agent Systems in Claude Code**: treating RAG as one tool an agent can choose to use, the spectrum from lightweight routing up to full ReAct-style dynamic planning, how multiple agents coordinate, and how to evaluate a RAG system once it's built. None of that is covered in this module.
