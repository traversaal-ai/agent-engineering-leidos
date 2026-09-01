# Reference: Naive RAG's Pain Points, and Enterprise RAG

Deep dive on Concepts 7 and 8 of the lesson. Where the three-stage pipeline in `rag-pipeline.md` breaks down at real-world scale, and what gets added to fix it.

## Naive RAG, restated

The pipeline from `rag-pipeline.md` in its simplest form:

```
1. load documents -> 2. generate document chunks -> 3. vectorize chunks -> 4. store embeddings + chunk ID  -> Vector DB
                                                                                                                    |
Question -> 5. vectorize question -> 6. use question embedding to retrieve relevant chunk IDs from Vector DB ------
                                                          |
                                     7. use chunk IDs to retrieve the actual chunks from storage
                                                          |
                     8. use question + relevant chunks + prompt to answer  -> LLM -> 9. generated answer
```

This works. It is also where most people stop, and it has real, specific failure modes once you put it in front of real questions on real enterprise data.

## Pain points of naive RAG, in general

Given the query "What are the security best practices?" against top-K chunk retrieval with no further processing:

| Pain point | What goes wrong |
|---|---|
| **Irrelevant retrieval** | Retrieves chunks that are not actually relevant to the query, e.g. pulling "company history" or "marketing strategy" chunks alongside genuinely relevant "security policy" chunks, just because they scored in the top K. |
| **No context awareness** | Does not consider the context or relationships between chunks, each chunk is scored and retrieved independently, with no sense of which chunks belong together. |
| **Information overload** | Too much unnecessary information is passed to the LLM, diluting the signal the model actually needs. |
| **Confusing answers** | The LLM, confused by irrelevant information mixed into its context, generates off-topic, incomplete, or even hallucinated responses. |
| **Poor efficiency** | Higher token usage, slower response time, and higher cost, from sending chunks the answer never needed. |

A second, sharper failure mode: naive RAG has **no permissions model**. A vector database with no access control returns whatever is semantically closest to the query, regardless of who is asking. A summer intern asking "What did the CEO talk about with the board today?" can retrieve and be shown board-level financial detail ("the company will have to lay off interns too... we have 3 months of runway left") purely because that text happened to be the closest semantic match, with nothing in the naive pipeline aware that this content should never reach this user.

## Four specific pain points, each with its own shape

**1. Struggles to summarize.** Retrieval returns chunks, not the whole picture, and naive RAG is weak at synthesizing across many documents. Given a document split into four chunks, a query like "Summarize what X does" only retrieves the one chunk that scored highest (a single "correct" match), while the other three chunks, which together held the rest of the actual summary, never make it into the prompt. The resulting answer is accurate as far as it goes, and incomplete because whole sections of context were never retrieved at all.

**2. Comparison is a headache.** A query like "Compare the parental leave policies for employees in Dubai vs. Abu Dhabi, and tell me which is more generous" gets embedded as one single vector and searched once. The top-5 chunks returned are whatever is closest to that blended, multi-part embedding, which in practice tends to skew toward one side of the comparison (e.g. only Dubai leave policy chunks appear), producing a confused, half-complete comparison. What should happen instead: break the query into sub-questions ("Describe Dubai parental leave," "Describe Abu Dhabi parental leave"), retrieve for each sub-question separately, and only then compare the two retrieved sets. Naive RAG has no mechanism to do that sub-query breakdown on its own.

**3. Implicit data, beyond the obvious.** A query like "What city is known for its love of jazz music?" or "Find the author of document X, then find their other publications, then summarize the common themes" needs **multi-hop reasoning**: the answer isn't stated verbatim anywhere, it requires chaining multiple retrievals together (find the author -> find their other publications -> summarize the themes). Standard RAG retrieves once, generates an answer based on that single retrieval, and stops. It has no mechanism for chaining a second retrieval based on what the first one found, so multi-hop questions come back incomplete or simply wrong.

**4. No memory, disconnected dialogue.** Without memory, each turn in a conversation is handled in isolation: told "Alice has a parrot" and then "Bob has two cats," a memory-less system asked "How many pets do Alice and Bob have?" cannot answer, because it has no record that those two facts were ever stated. With memory, the same two facts persist across turns and the system can correctly answer "Alice has one pet, a parrot, and Bob has two pets, two cats." Naive RAG, treating every query as a fresh, standalone retrieval, has no conversational memory by default.

## The better solution: Enterprise RAG

Enterprise RAG is the naive pipeline with purpose-built stages inserted around it to address every pain point above:

```
                                      Monitoring & Observability
                                     (wraps the whole pipeline)
                                              ^
                    Memory (Context & History)|  Feedback loops
                              ^                |       ^
User Query -> Input Guardrail -> Semantic Cache -> Query Rewriter -> Agentic Router -> LLM Generation -> Output Guardrail -> Final Answer
                                                                          |    ^            |
                                                                   Access Control            Citation & Provenance
                                                                          |
                                                          KB: Financial | KB: Technical Docs | KB: HR Policies
```

What each stage is for, and which pain point it answers:

| Stage | What it does | Pain point it addresses |
|---|---|---|
| **Input Guardrail** | Filters or blocks unsafe, out-of-scope, or malicious queries before they reach anything else. | General safety, not specific to any one pain point above. |
| **Semantic Cache** | Recognizes when a new query is semantically the same as one already answered, and reuses the answer instead of re-running retrieval and generation. | Poor efficiency: cuts token usage, latency, and cost for repeat or near-duplicate questions. |
| **Query Rewriter** | Rewrites or decomposes the raw query, e.g. into sub-questions for a comparison, or into a self-contained question given prior conversation turns. | Comparison is a headache; no memory (rewriting can fold in conversational context). |
| **Memory (Context & History)** | Persists facts and prior turns of the conversation, feeding both the rewriter and the router. | No memory, disconnected dialogue. |
| **Agentic Router**, with **Access Control** | Decides which knowledge base(s) a query should be answered from (Financial, Technical Docs, HR Policies, ...), and enforces who is allowed to see what before retrieval even happens. | No context awareness; irrelevant retrieval; the permissions gap (the intern/CEO example above). |
| **LLM Generation** | Generates the answer from the routed, access-controlled context. | Confusing answers, once the input context is already clean, the model has less room to go off-topic. |
| **Citation & Provenance** | Attaches sources to claims in the generated answer, feeding back as a signal for monitoring. | Trustworthiness and auditability, letting a human verify a claim against its source. |
| **Output Guardrail** | Checks the generated answer before it's shown to the user (safety, policy compliance, tone). | General safety, symmetric to the input guardrail. |
| **Monitoring & Observability, Feedback Loops** | Wraps the whole pipeline, tracking quality over time and feeding signal back into the router and cache. | Ongoing quality, not a single pain point, this is what lets you catch and fix a new failure mode after launch rather than only at design time. |

### Benefits of Enterprise RAG, summarized

- **Improved accuracy and relevance**, through advanced filtering and better use of context (the router, the guardrails).
- **Optimized retrieval**, ensuring data relevance with hybrid search and dynamic embeddings.
- **Enhanced query handling**, making retrieval precise through query rewriting and metadata.
- **Efficiently handling large datasets**, maintaining performance through better indexing as the corpus grows.
- **Refined initial results**, achieving accuracy through reranking and context compression after the first retrieval pass.

**Check:** Match each of the four specific pain points (struggles to summarize, comparison is a headache, implicit data / multi-hop, no memory) to the single Enterprise RAG stage above most directly responsible for fixing it. Is there one pain point that this architecture only partially fixes, one that would still benefit from an agent actively deciding to retrieve *again* based on what it just found, rather than the router simply picking a knowledge base once up front? Hold onto that question, it's exactly where next class's material on Agentic RAG and multi-agent systems picks up.
