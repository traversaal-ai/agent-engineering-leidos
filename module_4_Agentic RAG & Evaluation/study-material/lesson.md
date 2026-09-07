# Module 4: Agentic RAG & Evaluation

## Learning outcomes for Module 4

By the end of this module you can:

- Explain Naive RAG and its pain points (recap from Module 3)
- Describe what Agentic RAG is
- Explain routing, decomposition (one-shot query planning), and semantic caching
- Compare Naive RAG vs. Agentic RAG
- Place a RAG failure on the Five Pillars of Evaluation and name the domain it belongs to
- Describe Level 3 Retrieval Evals: relevance, recall, and precision, and what each key metric is sensitive to
- Describe Level 4 Generation Evals, and tell a retrieval-half failure apart from a generation-half one

---

## Recap from Module 03

Before this module starts, you should be comfortable with:

- Introduction to Naive RAG & Enterprise RAG
- What chunking is, and why we need it
- The different chunking strategies in RAG
- Naive RAG and its pain points

If any of that feels shaky, go back through Module 3's `study-material/lesson.md` and `reference/` folder first, this module builds directly on top of it.

## Where this fits in the course

```
WEEK 1              WEEK 2                  WEEK 3                  WEEK 4 (this module)     WEEK 5                  WEEK 6                    WEEK 7
Intro to AI          Skills, CLAUDE.md &     Enterprise RAG          Sub-Agents,               Voice Agents &          Guardrails,               Demo Day
Agents & Agent       Agent Operating         Systems                 Multi-Agent               Conversational          Evaluations &
Harness              System                                          Foundations &              Interfaces              Reliability
                                                                       Coordination
```

Week 4's own course-overview slide describes itself this way: build retrieval, reranking, rewriting, and grounding; add chunking for better retrieval; use sub-agents for specialized tasks; coordinate agents with shared state and tools; design patterns for multi-agent collaboration.

---

## Concept 1: Stage 1, Ingestion — Parse, Chunk, Embed, Store (recap)

Turn raw data into **searchable knowledge**.

```
1. Data Sources          2. Load & Extract        3. Chunk               4. Embed                5. Store
   Documents,               Load files and           Split into              Convert chunks           Store embeddings
   Web Pages,                extract raw text          smaller,               into embeddings           in a vector
   Databases, APIs                                       meaningful                                       database
   (Parsers, OCR,                                       chunks                (Embedding model,          (Vector Database,
    Text Extractors)                                    (Chunking Strategy:     e.g. text-embedding-3)     e.g. Pinecone, Qdrant)
                                                          size, overlap)
```

**Goal:** Make your data machine-readable and semantically searchable so it can be used by LLMs to generate accurate, grounded answers.

## Concept 2: Stage 2, Retrieval — Turning a Question Into a Search (recap)

Find the **right context** from your data.

```
1. User Query                    2. Embed Query            3. Search Vector Database        4. Retrieve Relevant Chunks
   "What are the pricing            Convert the query          Find similar embeddings         Chunk 1 (score 0.92)
    options for the                  into an embedding          using similarity search          Chunk 2 (score 0.87)
    enterprise plan?"                                            (e.g. cosine similarity)         Chunk 3 (score 0.83)
```

**Goal:** Retrieve the most relevant and useful context from your data to ground the model's response.

## Concept 3: Stage 3, Generation — Augment (Query + Retrieved Context) → LLM Response (recap)

Turn retrieved context into **accurate, grounded answers**.

```
1. Retrieved Chunks       2. Build Prompt              3. Generate Answer      4. Post-process              5. Final Answer
   Chunk 1, 2, 3              Assemble context,             LLM generates a         Verify & ground,              Deliver a grounded,
                                query, and instructions       response using the      filter/guardrails,             clear answer with
                                                               provided context        add citations                  sources
```

**Goal:** Generate accurate, trustworthy, and well-cited answers that are grounded in your data.

**Putting it all together, the full RAG pipeline:**

```
1. load documents -> 2. generate document chunks -> 3. vectorize chunks -> 4. store embeddings with document chunk ID -> Vector DB
                                                                                                                              |
Question -> 5. vectorize question -> 6. use question embedding to retrieve relevant document chunk ID from Vector DB -------|
                                                              |
                                    7. use document chunk IDs to retrieve document chunks from storage
                                                              |
                    8. use question + relevant document chunks + prompt to answer -> LLM -> 9. generated answer
```

## Concept 4: Chunking and chunking strategies (recap)

**Chunk size matters.** Chunking involves breaking up your data into smaller pieces, or chunks, as large language models have a limited context window and cannot take in your entire dataset at once.

**Importance of chunking:** improved retrieval efficiency, enhanced accuracy and relevance, scalability and manageability, balanced information distribution.

**ChunkViz** makes chunk size and overlap directly visible: paste in text, set a chunk size and overlap, and it highlights different chunks in different colors, chunks having overlapping text in a separate color, and, importantly, flags a chunk changing in the middle of a sentence as **not good**.

**The five chunking strategies, different ways to split a document:**

| # | Strategy | What it means | Example: Input → Chunks |
|---|---|---|---|
| 1 | **Fixed-Size Chunking** | Specified number of characters, regardless of their content or structure. | Input text -> Chunk 1, Chunk 2, Chunk 3, ... |
| 2 | **Recursive Chunking** | Divides the input text into smaller chunks in a hierarchical and iterative manner using a set of separators (operates recursively until the desired size or structure is achieved). | Input text -> a tree of progressively smaller chunks |
| 3 | **Document Based Chunking** | Split a document based on its inherent structure (headings, sections, etc.). | Document with H1 Title, H2 Section 1, H2 Section 2, H1 Conclusion -> Title, Section 1, Section 2, Conclusion chunks |
| 4 | **Semantic Chunking** | Divides the text into meaningful, semantically complete chunks. | Input text -> Chunk 1, 2, 3 (meaningful) |
| 5 | **Agentic Chunking** | LLM determines how much and what text to include in a chunk, based on context. | Input + Context/Query -> Chunk 1, 2, 3 (relevant, LLM-determined) |

**Worked example, Recursive Chunking.** Input (108 characters): *"AI is amazing. It is used in medicine, finance, and art. However, it also raises ethical concerns."* Chunking rules: max chunk size 50 characters; separators in priority order `[".", ",", " "]`. Too long, so it's split using `". "` (sentence split) first, producing: `"AI is amazing."` (15), `"It is used in medicine, finance, and art."` (43), `"However, it also raises ethical concerns."` (49). Final chunks: those three strings. **How it's recursive:** if either resulting chunk were still longer than 50 characters, that specific chunk would be recursively re-split using the next separator.

**Worked example, Document Based Chunking.** Document-Based Chunking splits a document using its inherent structure (e.g., headers, sections, paragraphs) rather than character limits. A document with `## Introduction`, `## Applications`, `## Challenges`, `## Conclusion` sections is split, by top-level headers, into exactly four chunks: Chunk 1 (Introduction), Chunk 2 (Applications), Chunk 3 (Challenges), Chunk 4 (Conclusion).

## Concept 5: Naive RAG pain points (recap)

**Pain Point 1: Struggles to Summarize.** Retrieval returns chunks, not the whole picture; weak at synthesizing across many documents. Example: a document about Blueteam AI is split into four chunks; the query "Summarize what Blueteam AI does" retrieves only one chunk (the one that matches best) and the retriever marks the other three as not retrieved, missing context from unretrieved chunks. The resulting prompt only contains the one retrieved chunk, so the answer is based on incomplete information.

**Pain Point 2: Comparison is a Headache.** "Compare candidate A's and B's open-source contributions" needs two retrievals held at once. In the erroneous flow: the entire complex query is embedded as one vector, the top 5 chunks are retrieved, and the system generates an answer missing half the comparison (e.g. only Dubai leave data is mentioned, Abu Dhabi is missing), a confused comparison. What should happen instead: break the query into sub-questions (e.g. "Describe Dubai parental leave," "Describe Abu Dhabi parental leave"), retrieve for each separately, then compare, producing a complete comparison (e.g. "Abu Dhabi has up to 90 days, Dubai has up to 45 days, Abu Dhabi is found to be more generous").

**Pain Point 3: Implicit Data — Beyond the obvious.** "What city is known for its love of jazz music?" the answer isn't stated verbatim anywhere, it needs inference. This is **complex multi-hop reasoning**: e.g. "Find the author of document X, then find their other publications, then summarize the common themes" requires chaining multiple retrievals together (find author -> find publications -> summarize themes). Key issues: standard RAG had no mechanism for chaining retrievals, the system retrieved once, generated an answer based on that single retrieval, and stopped, failing to break down complex questions into sequential steps, resulting in a stopped/incomplete answer.

**Pain Point 4: No memory — Disconnected dialogue.** Without memory: told "Alice has a parrot," then "Bob has two cats," asked "How many pets do Alice and Bob have?", the system replies "It is impossible to answer this question without more information." With memory: the same two facts persist, and the system correctly answers "From what you've told me, Alice has one pet, a parrot, and Bob has two pets, two cats."

**Better solution: Enterprise RAG.**

```
                                          Monitoring & Observability
                                     Memory (Context & History)   Feedback Loops
                                              ^                        ^
User Query -> Input Guardrail -> Semantic Cache -> Query Rewriter -> Agentic Router -> LLM Generation -> Output Guardrail -> Final Answer
                                                                          |    ^            |
                                                                   Access Control     Citation & Provenance
                                                                          |
                                                          KB: Financial | KB: Technical Docs | KB: HR Policies
```

**Benefits of Enterprise RAG:** Improve Accuracy and Relevance (enhancing data precision through advanced filtering and context use); Optimize Retrieval (ensuring data relevance with hybrid search and dynamic embeddings); Enhance Query Handling (making retrieval precise with query rewriting and metadata); Efficiently Handle Large Datasets (maintaining high performance with better indexing); Refine Initial Results (achieving accuracy through reranking and context compression).

---

## Concept 6: Introduction to Agentic RAG

**Agentic RAG = Agent-based RAG implementation.** Agentic RAG utilizes intelligent agents that can plan, reason, and learn over time.

```
Query -> Agents? -> RAG -> Agents? -> Response
```

**RAG is just one Tool:** Agents can decide to use RAG with other tools.

The spectrum from simple to advanced:

```
Agent Ingredients (Simple, Lower Cost, Lower Latency)     |   Full Agents (Advanced, Higher Cost, Higher Latency)
Routing, Tool Use, One-Shot Query Planning,               |   ReAct, Dynamic Planning + Execution
Conversation Memory                                        |
```

### Routing

Simplest form of agentic reasoning that uses an LLM to pick the downstream RAG pipeline. A Router (backed by an LLM, e.g. OpenAI GPT) picks between tools, e.g. a RAG Summary Query Engine or a RAG Vector Query Engine, to produce the Response.

### One-Shot Query Planning

Break down a query into **parallelizable sub-queries**. Each sub-query can be executed against any set of RAG pipelines. Once the results of the sub-queries are generated, they are synthesized into a final response. An LLM decomposes the input query into sub-queries and calls the appropriate RAG query engine(s); the individual sub-responses are synthesized to generate the final output based on the agent's instructions.

### Tool Use

Use an **LLM to call an API and infer the parameters of that API**. An LLM generates the args/params for the external API, SQL statement, etc., from the input query. The tool makes the call (to an External API, SQL DB, Vector DB, Open Weather Map, or similar), and the Agent then synthesizes the final response based on the agent's instructions and output parsers, if any.

### Conversation Memory

The memory is just a **flat list of the conversations** the agent had with the user. On a new message, the agent reasoning loop fetches conversation history, sends tool input and receives tool output as needed, and stores the updated conversation history.

### Demo: Naive RAG vs. Agentic RAG

The module walks through a live, side-by-side demo comparing a Naive RAG pipeline against an Agentic RAG pipeline.

---

## Concept 7: The Five Pillars of Evaluation

Concepts 1-6 were about building a retrieval system and then giving an agent the judgement to use it. This half of the module is about the question that follows immediately: **how do you know it works?**

"It seems fine" is not an answer you can act on. Evaluation gives you a place to stand, a hierarchy of capability called the **Five Pillars**, where each level assumes the one beneath it already works.

```
                    Level 5: Agent Evals              -> Domain 3: The Agent Interface
        Level 4: Generation Evals
    Level 3: Retrieval Evals                          -> Domain 2: The RAG Engine  (this module's focus)
Level 2: Reasoning Evals
Level 1: LLM Quality + Efficiency Evals                -> Domain 1: The LLM Core
```

The five levels group into **three domains**: Domain 1, The LLM Core (Levels 1-2), Domain 2, The RAG Engine (Levels 3-4), and Domain 3, The Agent Interface (Level 5).

Each level exists to answer one question:

| Level | Core question |
|-------|---------------|
| 1. LLM Quality + Efficiency | Is the underlying model good enough, and cheap and fast enough, to build on at all? |
| 2. Reasoning | Can the model actually reason over what it is given? |
| 3. Retrieval | Can the system find the right information efficiently? |
| 4. Generation | Is the final answer grounded in the retrieved documents? |
| 5. Agent | Does the agent, using the whole stack as tools, accomplish the task it was given? |

**Why the order matters.** The pyramid is a pyramid because each level rests on the one below. Asking "did the model use its context faithfully?" is meaningless if the retriever handed it the wrong context in the first place. The same logic runs all the way up: a Level 5 agent failure is very often a Level 3 retrieval failure wearing a costume.

This module goes deep on **Domain 2, The RAG Engine**: Levels 3 and 4. Levels 1, 2 and 5 are named here for orientation only.

---

## Concept 8: Level 3, Retrieval Evals

**Core question:** Can the system find the right information efficiently?

A powerful reasoning engine is useless if it operates on flawed or incomplete information. This pillar measures the retrieval system that feeds context to the LLM, specifically the **relevance, recall, and precision** of the sources it cites.

```
[Vector DB + retrieval pipeline] -> [Context Filter] -> Evaluation Focus:
                                                          - Relevance: Does the retrieved context
                                                            directly answer the query?
                                                          - Recall: Did the system pull all
                                                            necessary documents?
                                                          - Precision: Is the retrieved data
                                                            free of distracting, irrelevant noise?
```

**Common benchmark datasets:** **BEIR (Benchmarking-IR)**, a diverse collection of information retrieval tasks; **MS MARCO**, a large-scale dataset for passage ranking and reading comprehension; and **Natural Questions (NQ)**, queries from real Google search users that require finding answers in Wikipedia articles.

**Key performance metrics:**

| Metric | What it measures | What it's sensitive to |
|--------|------------------|------------------------|
| NDCG@k | Ranking quality, rewarding highly relevant documents placed at the top | *Order* |
| Recall@k | What percentage of all relevant documents were found in the top k | *Completeness* |
| Precision@k | Of the top k retrieved, what percentage were relevant | *Cleanliness* |
| MRR (Mean Reciprocal Rank) | The rank of the first correct answer | *How fast* the first right answer shows up |

The right-hand column is the part worth memorizing. These four metrics are not four ways of saying the same thing, they disagree on purpose. A relevant document buried at position 10 scores worse under NDCG@k than the same document at position 1, but Recall@k cannot tell the two situations apart at all.

**One result set, four different scores.** Take a query against a knowledge base holding **5 relevant documents in total**. The retriever returns the top 5 (`R` = relevant, `x` = not):

```
rank:      1     2     3     4     5
result:    x     R     R     x     R
```

- **Recall@5** = 3 relevant found / 5 that exist = **0.60**. Two relevant documents never surfaced.
- **Precision@5** = 3 relevant / 5 returned = **0.60**. Two slots wasted on noise.
- **MRR** = 1 / 2 (first relevant is at rank 2) = **0.50**. Blind to everything below rank 2.
- **NDCG@5** is the only one of the four that would change if you *reordered these same five results* without adding or removing any.

Recall@5 and Precision@5 tie at 0.60 here only because k happens to equal the number of relevant documents; they answer different questions and diverge the moment that stops being true. And the practical consequence: **a reranker changes order, not membership**, so it can only move NDCG@k and MRR. If two relevant documents never made the top 5 at all, no reranker will save you, that is a recall problem living upstream in chunking, embedding, or retrieval depth.

See `../reference/rag-evaluation.md` for the full deep dive.

---

## Concept 9: Level 4, Generation Evals

**Core question:** Is the final answer grounded in the retrieved documents?
**Core challenge:** preventing hallucination.

This is the test that the LLM isn't "freelancing" with its creativity. Level 3 asked whether the right material reached the model; Level 4 asks what the model then did with it. Unlike Level 3, this level leans less on standard benchmarks and more on metrics that judge the generation *relative to the retrieved context*:

- **Faithfulness**: Does the generated answer directly follow from the provided context? A direct measure against hallucination.
- **Answer Relevancy**: Is the answer relevant to the user's original query?
- **Context Precision**: Is the retrieved context necessary and concise for the query? (Signal-to-noise ratio.)
- **Context Recall**: Did the retriever find everything needed to answer completely?

Plus, on generation quality specifically: **Faithfulness** (response stays within retrieved context), **Groundedness** (claims are supported by source data), **Hallucination Rate** (frequency of unsupported outputs), and **Completeness** (covers all aspects of the query).

```
Retrieved Facts  ->  Synthesis Filter  ->  Faithful Output
[Evaluate: Retrieval Quality]         [Evaluate: Generation Quality]
```

**The two halves, and why the distinction pays for itself.** Look at where that list splits. Context Precision and Context Recall are about the **retrieval half**, do you even have the right material. Faithfulness, Groundedness, Hallucination Rate and Completeness are about the **generation half**, given that material, did the model use it correctly and fully.

A RAG system can fail at either half independently: perfect retrieval with a model that ignores its context and hallucinates anyway, or flawless, faithful generation built on incomplete retrieved context. So given a bad answer, **read the retrieved context before you read the answer**. If the material needed wasn't in it, you have a Context Recall problem and every generation metric is misleading, the model was never given a chance. Only once the context is right does a wrong answer become a genuine generation failure: an unsupported claim is caught by Faithfulness and Groundedness, a half-answer by Completeness, an answer about the wrong thing entirely by Answer Relevancy.

The trap this avoids is tuning prompts to fix what is actually a retrieval bug.

**And this is where the module's two halves meet.** Agentic RAG doesn't escape the pyramid, it just moves where failures originate. A **Router** picking the wrong knowledge base is a Level 3 failure, and the generator may then be perfectly faithful to context that came from the wrong place, so Faithfulness stays high while the answer is useless. **One-Shot Query Planning** raises Context Recall on comparison and multi-hop queries, but adds a synthesis step where the final answer can drift from what any individual sub-query retrieved, a Level 4 risk naive RAG doesn't have. Every decision point agency adds is a new place for a failure to originate.

See `../reference/rag-evaluation.md` for the full deep dive on both levels.

---

## Key Takeaways

1. **RAG is just one tool.** The reframe at the heart of Agentic RAG is that a query no longer has to travel the same fixed retrieval path every time, an agent decides whether and how to retrieve.
2. **Four agent ingredients** — Routing, One-Shot Query Planning, Tool Use, Conversation Memory — buy most of the benefit at the simple, lower-cost, lower-latency end of the spectrum, before you reach for Full Agents (ReAct, Dynamic Planning + Execution).
3. **Agency is not free.** Every decision point you add is a new place for a failure to originate, which is exactly why evaluation stops being optional once RAG becomes agentic.
4. **Evaluation is a pyramid, not a checklist.** Five levels across three domains, and each level assumes the one beneath it works. A Level 5 agent failure is often a Level 3 retrieval failure in disguise.
5. **A RAG answer has two halves that fail independently.** Retrieval (Context Precision, Context Recall) and generation (Faithfulness, Groundedness, Hallucination Rate, Completeness). Read the retrieved context before you judge the answer.
6. **Retrieval metrics disagree on purpose.** NDCG@k cares about order, Recall@k about completeness, Precision@k about cleanliness, MRR about how fast the first right answer appears. Pick the one that matches the failure you actually have.
7. **Reranking changes order, not membership.** It can move NDCG@k and MRR but never Recall@k, so a document that never made the top k is an upstream problem, not a ranking one.

---

## Appendix: Key terms to remember

- **Faithfulness**: Does the generated answer directly follow from the provided context? The most direct measure against hallucination.
- **Groundedness**: Whether the claims in a response are supported by the source data.
- **Hallucination Rate**: The frequency of unsupported outputs.
- **Context Precision**: Is the retrieved context necessary and concise for the query? (Signal-to-noise ratio.)
- **Context Recall**: Did the retriever find all the information needed to answer the query completely?
- **NDCG@k**: Measures ranking quality, rewarding highly relevant documents placed at the top. The only common retrieval metric that responds to reordering alone.
- **MRR (Mean Reciprocal Rank)**: Measures the rank of the first correct answer, and nothing below it.

## Summary

1. Naive RAG's Ingestion/Retrieval/Generation pipeline, chunking strategies, and pain points (summarize, comparison, implicit/multi-hop, memory) carry over from Module 3, and Enterprise RAG's stages address them.
2. Agentic RAG treats RAG as one tool an agent can choose to use. Four "agent ingredients" — Routing, One-Shot Query Planning, Tool Use, Conversation Memory — sit on the simple/cheap/low-latency end of a spectrum that runs up to "Full Agents" (ReAct, Dynamic Planning + Execution).
3. Evaluation answers the question building leaves open: does it work? The Five Pillars pyramid groups five levels into three domains, and this module goes deep on Domain 2, The RAG Engine: Level 3 Retrieval Evals (relevance, recall, precision; BEIR/MS MARCO/NQ; NDCG@k, Recall@k, Precision@k, MRR) and Level 4 Generation Evals (faithfulness, groundedness, hallucination rate, completeness).
4. The two halves of a RAG answer fail independently, so diagnosis has an order: check whether the right material was retrieved before asking whether the model used it faithfully.

## Where to next

Do `exercises.md` for hands-on practice with agentic RAG design and evaluation diagnosis, including computing the retrieval metrics by hand. Or ask to be quizzed (`quiz.md`). For the fuller treatment of both evaluation levels, including the worked metric example and how the agent ingredients shift where failures originate, see `../reference/rag-evaluation.md`.
