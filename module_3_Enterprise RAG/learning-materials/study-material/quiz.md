# Module 3: Quiz

## Q1. Why can't you just paste your entire document library into an LLM prompt?
- Type: recall
- **Answer:** Two hard limits: the context window (a fixed number of tokens the model can attend to, content outside it is ignored, not remembered) and cost/latency (every token sent costs money and adds response time, most of which would be irrelevant to any single question).
- **Hint:** One limit is about what the model can even see. The other is about what it costs you even when it can see it.

## Q2. What does "Augmented" in Retrieval-Augmented Generation actually refer to?
- Type: explain-why
- **Answer:** The retrieved chunks are added to (augment) the prompt before the LLM generates its answer. They don't replace the LLM's own reasoning, they ground it in real data instead of the model's training-time memory.
- **Hint:** What specifically gets added to what, and at which stage?

## Q3. Why does a vector search for "kitten" return results about "cat" and "dog," when a keyword search for the same term would not?
- Type: explain-why
- **Answer:** Embeddings place semantically similar items close together in vector space regardless of shared characters. Vector search returns items based on that geometric/semantic closeness, not exact term matches, while keyword search requires the literal characters to match.
- **Hint:** What does an embedding actually encode, meaning or spelling?

## Q4. A relational database and a vector database both hold "your data." What's the actual division of labor between them in a RAG system?
- Type: application
- **Answer:** The relational database is the system of record: structured rows, columns, foreign-key relationships, found via exact-match SQL. The vector database is the semantic retrieval layer built from it: high-dimensional embeddings, found via approximate nearest-neighbor search. They're used together, not as substitutes for each other.
- **Hint:** Which one would you query for "every invoice for customer #4521," and which for "documents discussing billing complaints"?

## Q5. Name the three stages of any RAG pipeline, and the one-line goal of each.
- Type: recall
- **Answer:** Ingestion (parse, chunk, embed, store, make data machine-readable and semantically searchable), Retrieval (embed the query, search, retrieve the most relevant chunks), Generation (build a prompt from the retrieved chunks and query, generate and post-process an accurate, well-cited answer).
- **Hint:** One stage happens offline, ahead of time. The other two happen live, per query.

## Q6. Name the five chunking strategies, and in one phrase, what each one splits on.
- Type: recall
- **Answer:** Fixed-Size (a specified character count), Recursive (a prioritized list of separators, applied recursively), Document-Based (the document's own structure, e.g. headings), Semantic (where meaning shifts, via an embedding model), Agentic (an LLM decides, based on context).
- **Hint:** They run roughly cheapest-and-simplest to most expensive-and-context-aware.

## Q7. A RAG system, asked to "summarize what our product does" against a four-chunk document, only retrieves the single highest-scoring chunk and produces an accurate but incomplete summary. Which naive RAG failure shape is this, and why does it happen?
- Type: application
- **Answer:** "Struggles to summarize." It happens because top-K retrieval only returns the chunk(s) that scored highest against the query embedding; the other chunks, which together held the rest of the summary, are never retrieved at all, so the LLM never sees them.
- **Hint:** Is the LLM hallucinating here, or is it faithfully answering from an incomplete set of chunks?

## Q8. Why does naive RAG struggle with a comparison query like "which vendor has the better SLA, Acme or Globex," even though both vendors' SLA documents exist in the corpus?
- Type: explain-why
- **Answer:** The whole comparison query gets embedded as one blended vector and searched once, which in practice skews toward whichever side of the comparison is closer in embedding space, rather than retrieving both sides evenly. Naive RAG has no mechanism to break the query into "describe Acme's SLA" and "describe Globex's SLA" as separate retrievals.
- **Hint:** How many times does naive RAG search the vector database for a query like this, one, or one per thing being compared?

## Q9. What is naive RAG's "no permissions model" problem, specifically?
- Type: explain-why
- **Answer:** A vector database with no access control returns whatever is semantically closest to the query, regardless of who's asking. Naive RAG has nothing that checks whether the requesting user is allowed to see the content of a chunk before retrieving and returning it, so a low-privilege user can retrieve high-privilege content purely because it scored as the closest semantic match.
- **Hint:** Is this a retrieval-quality problem, or a completely different kind of problem?

## Q10. Match each Enterprise RAG stage to the naive RAG pain point it's built to fix: Semantic Cache, Query Rewriter, Memory, Agentic Router + Access Control.
- Type: recall
- **Answer:** Semantic Cache = poor efficiency (reuses answers for semantically duplicate queries). Query Rewriter = comparison headaches (decomposes into sub-questions) and helps with memory (folds in conversational context). Memory (Context & History) = no memory, disconnected dialogue. Agentic Router + Access Control = no context awareness / irrelevant retrieval, and the permissions gap (routes to the right knowledge base and checks who's allowed to see it before retrieval).
- **Hint:** One stage is about repeat questions. One is about breaking a question apart. One is about remembering prior turns. One is about both "where to look" and "who's allowed to look."

## Q11. Of naive RAG's four specific failure shapes (summarization, comparison, multi-hop, memory), which one does the Enterprise RAG architecture from this module only partially fix, and why?
- Type: explain-why
- **Answer:** Multi-hop reasoning (the "implicit data" pain point). The Agentic Router picks a knowledge base once, up front; it doesn't chain a second retrieval based on what the first one found. Fully solving multi-hop questions needs an agent that reasons, retrieves, observes the result, and decides whether to retrieve again, which is next class's material (Agentic RAG and multi-agent systems), not something this module's architecture does on its own.
- **Hint:** Does routing to the right knowledge base, once, help you if the answer requires two retrievals in sequence, where the second depends on the result of the first?
