# Reference: Embeddings, Vector Databases, and the RAG Pipeline

Deep dive on Concepts 3 through 5 of the lesson. Background on the machinery that makes retrieval possible before looking at chunking or Enterprise RAG.

## Why RAG exists at all

Two separate limits force the issue:

1. **The context window limit.** An LLM's context window has a fixed number of target tokens it can attend to at once. A blog post is roughly 1,000 tokens; an encyclopedia is roughly 2,000,000. Even a single internal wiki or contract set overflows what you can paste into a prompt. When user input plus LLM output exceeds the window, content outside the window is simply ignored by the model, not remembered and not used.
2. **The cost and latency limit.** Even when a document *does* fit, every token you send costs money and adds latency. Model pricing is charged per million input and output tokens; stuffing a full document into every query multiplies that cost by however many queries you ask, for no benefit if only one paragraph was actually relevant.

The underlying problem beneath both: **LLMs don't know your data.** A model like Claude or GPT was trained on public internet text. It has never seen your company's contracts, your Slack history, or last week's status report, because those are internal to your organization. Asked about them directly, it will guess, and guessing from a language model is exactly what produces hallucination.

**Retrieval Augmented Generation (RAG)** is the fix: instead of trying to fit all your knowledge into the prompt, store it somewhere you can search, retrieve only the relevant pieces for a given question, and hand just those pieces to the LLM. This is also what Enterprise Knowledge Management (EKM) is trying to solve at the organizational level: EKM is the systematic process by which organizations capture, store, manage, and share their collective knowledge. RAG is the technical mechanism that makes EKM queryable by an LLM.

## Embeddings: turning meaning into numbers

An **embedding** is the numerical representation of a piece of data, text, an image, or audio, as a vector (a list of numbers). Similar meanings end up as vectors that are close together in that space, regardless of whether the two pieces of text share any of the same words.

```
cat  => [1.2, -0.1,  4.3,  3.2, ...]
mat  => [0.4,  2.5, -0.9,  0.5, ...]
on   => [2.1,  0.3,  0.1,  0.4, ...]
```

The dimensionality varies by model (a few hundred to a few thousand numbers per vector), but the principle is the same regardless of size: an **embedding model** converts each object (a document chunk, an image, an audio clip) into a vector, and all of those vectors live together in the same vector space, where geometric closeness stands in for semantic closeness.

This is what makes **vector search** different from keyword search: a query for "kitten" can retrieve results near "cat" and "dog" (semantically close, in the "animals" region of the space) without ever containing the word "cat," because vector search returns similar items based on their semantic meaning, not exact term matches. Keyword search would miss that connection entirely, since none of the literal characters match.

## Vector databases: finding what's similar, fast

A **vector database** stores millions of embeddings and finds the most similar ones in milliseconds. It searches by meaning, not keywords.

The query path, in plain terms:

```
Your question  ->  [0.81, 0.15, 0.65, ...]     (embed the query)
      |
      v  similarity search
Vector DB: ●●●●●●●●●●
      |
      v
Top 3 matching chunks returned
```

Under the hood, a vector database maintains two parallel paths:

- **Write path:** raw data (text, images, audio) goes through an embedding model to become a vector, gets paired with metadata (source, timestamps, permissions), and is written into an index (commonly an HNSW graph, a multi-layer proximity structure built for fast approximate search) alongside a separate metadata index.
- **Query path:** the query goes through the same embedding model, and the resulting vector is compared against the stored vectors using a similarity metric (commonly cosine similarity), returning an **approximate nearest neighbor (ANN)** top-K result, the K vectors closest to the query in the embedding space.

Common vector database tools: Pinecone, Weaviate, Qdrant, pgvector (a Postgres extension). Pinecone and Weaviate are managed/cloud-first; Qdrant and pgvector can run self-hosted, which matters if your data has residency or compliance constraints.

### Vector database vs. relational database

These are not competitors, they answer different questions and are typically used together:

| | Relational Database | Vector Database |
|---|---|---|
| **Stores** | Rows and columns, with explicit relationships (foreign keys) | High-dimensional embeddings (e.g. a 1536-dimensional text embedding) |
| **Finds things by** | Exact match / structured query (SQL, B-tree index) | Semantic similarity (ANN search, e.g. HNSW graph + cosine similarity) |
| **Guarantees** | ACID transactions: commit or rollback, no partial writes | No transactional guarantee in the same sense; optimized for fast approximate search instead |
| **Typical tools** | PostgreSQL, MySQL, Oracle | Pinecone, Weaviate, Qdrant, pgvector |
| **Role in RAG** | System of record: the source documents and their structured metadata | Semantic retrieval layer: what actually gets searched to answer a question |

In a real RAG system, the relational database is usually still the source of truth for the raw data; the vector database is a derived index built from it, kept in sync through an embedding pipeline that feeds the RAG query flow.

## The three stages of RAG

Every RAG system, naive or enterprise, breaks down into the same three stages. Enterprise RAG (see `enterprise-rag-and-agentic-rag.md`) adds machinery around each stage, but the stages themselves don't change.

### Stage 1: Ingestion, turn raw data into searchable knowledge

```
1. Data Sources        2. Load & Extract     3. Chunk              4. Embed              5. Store
   Documents,             Load files and         Split into            Convert chunks         Store embeddings
   Web Pages,              extract raw text        smaller,              into embeddings         in a vector
   Databases, APIs                                  meaningful                                     database
                                                       chunks
   (Parsers, OCR,                                  (Chunking                (Embedding             (Vector DB, e.g.
    text extractors)                                 strategy: size,          model, e.g.            Pinecone,
                                                       overlap)                text-embedding-3)      Qdrant)
```

**Goal:** make your data machine-readable and semantically searchable so it can be used by LLMs to generate accurate, grounded answers. See `chunking-strategies.md` for step 3 in depth, it is the step most naive implementations get wrong.

### Stage 2: Retrieval, turning a question into a search

```
1. User Query                2. Embed Query           3. Search Vector DB          4. Retrieve Relevant Chunks
   "What are the pricing         Convert the query        Find similar embeddings      Chunk 1  (score 0.92)
    options for the                into an embedding        using similarity search      Chunk 2  (score 0.87)
    enterprise plan?"                                        (e.g. cosine similarity)     Chunk 3  (score 0.83)
```

**Goal:** retrieve the most relevant and useful context from your data to ground the model's response. The embedding model used here must be the *same* one used at ingestion time; a query embedded with a different model will not land in the right part of the vector space relative to your stored chunks.

### Stage 3: Generation, augment and answer

```
1. Retrieved Chunks    2. Build Prompt         3. Generate Answer     4. Post-process           5. Final Answer
   Chunk 1, 2, 3           Assemble system/         LLM generates a       Verify & ground,          Grounded,
                             instructions, user        response using       filter/guardrails,        clear answer
                             query, and retrieved       the provided          add citations              with sources
                             context                    context
```

**Goal:** generate accurate, trustworthy, and well-cited answers that are grounded in your data, not in whatever the model happened to memorize during training.

### The full pipeline, end to end

```
                         Indexing (offline, run ahead of time)
Documents -> Chunking -> Chunks -> Embedding model -> Vectorize -> Vector database (indexed)
                                                                          ^
                                                                          | Retrieve
User -> Query -> Embedding model -> Vectorize -> Search  --------------->|
                                                                          |
                                                                    Relevant contexts
                                                                          |
                                                                          v
                                                            Query + Prompts (Augment) -> LLM -> Generate -> Response -> User
```

The word "Augment" in Retrieval-**Augmented** Generation refers specifically to this last step: the retrieved chunks augment (are added to) the prompt before the LLM ever sees the question, they do not replace the LLM's own reasoning, they ground it.

**Check:** If the embedding model used at query time is different from the one used at ingestion time, what specifically breaks, and at which of the three stages does it break?
