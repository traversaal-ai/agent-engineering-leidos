# Glossary (Source of Truth)

Master list of terms for this module. `study-material/key-concepts.md` repeats the subset most relevant to the lesson itself; this file is the fuller reference.

- **RAG (Retrieval Augmented Generation)**: A technique that retrieves relevant pieces of external data and adds ("augments") them to an LLM's prompt before generation, so the model answers grounded in that data instead of only what it memorized during training.
- **Enterprise Knowledge Management (EKM)**: The systematic process by which organizations capture, store, manage, and share their collective knowledge. RAG is the technical mechanism that makes EKM queryable by an LLM.
- **Context window**: The fixed span of tokens (to the left and right of the current position) an LLM can attend to at once. Content outside the window is ignored by the model, not remembered.
- **Hallucination**: An LLM generating a confident but false or unsupported statement, most often because it lacks (or ignores) grounded data and fills the gap from its training-time priors.
- **Embedding**: The numerical representation (a vector) of a piece of data, text, image, or audio, produced so that semantically similar items end up close together in the same vector space.
- **Embedding model**: A model that converts raw data into its embedding vector, e.g. Voyage AI, OpenAI's text-embedding-3.
- **Vector search**: Search that returns similar items based on their semantic meaning (geometric closeness in embedding space) rather than exact keyword matches.
- **Vector database**: A database purpose-built to store millions of embeddings and find the most similar ones in milliseconds, e.g. Pinecone, Weaviate, Qdrant, pgvector.
- **ANN (Approximate Nearest Neighbor) search**: The search technique vector databases use to quickly find the top-K closest vectors to a query vector, without exhaustively comparing against every stored vector.
- **HNSW graph**: Hierarchical Navigable Small World graph, a common multi-layer index structure vector databases use to make ANN search fast.
- **Cosine similarity**: A common metric for how close two vectors are, based on the angle between them, used to rank retrieved results by relevance.
- **Chunking**: Breaking data into smaller pieces (chunks) before embedding and storing it, needed because LLMs and embedding models cannot process an entire dataset as one unit.
- **Fixed-Size Chunking**: Splitting text into chunks of a specified number of characters, regardless of content or structure.
- **Recursive Chunking**: Recursively splitting text using a prioritized set of separators until each chunk is under the target size, respecting sentence/clause boundaries where possible.
- **Document-Based Chunking**: Splitting a document according to its own inherent structure (headings, sections).
- **Semantic Chunking**: Dividing text into chunks that are semantically complete, using an embedding model to detect where meaning shifts.
- **Agentic Chunking**: Using an LLM to decide how much and what text to include in a chunk, based on context.
- **Chunk overlap**: A deliberate duplication of a few sentences or characters at chunk boundaries, so context isn't lost right at the cut point.
- **Ingestion (RAG Stage 1)**: Load, extract, chunk, embed, and store raw data so it becomes searchable knowledge.
- **Retrieval (RAG Stage 2)**: Embed a user's query and search the vector database for the most relevant chunks.
- **Generation (RAG Stage 3)**: Build a prompt from the retrieved chunks and the query, generate an answer, and post-process it (verify, filter, cite).
- **Naive RAG**: The basic three-stage RAG pipeline with no additional processing: retrieve top-K chunks by embedding similarity, hand them to the LLM, generate an answer.
- **Multi-hop reasoning**: Answering a question that requires chaining multiple retrievals together (e.g. find the author, then find their other work, then summarize it), rather than answering from a single retrieval pass.
- **Enterprise RAG**: A RAG architecture that wraps the naive pipeline with additional stages (guardrails, semantic cache, query rewriter, agentic router, access control, citation/provenance, monitoring) to address naive RAG's pain points at production scale.
- **Semantic cache**: A stage that recognizes when a new query is semantically equivalent to a previously answered one, and reuses the prior answer instead of re-running retrieval and generation.
- **Query rewriter**: A stage that rewrites or decomposes a raw query, e.g. into sub-questions for a comparison, or into a self-contained question given prior conversation turns.
- **Agentic router**: A stage that decides which knowledge base(s) a query should be answered from, and enforces access control before retrieval happens.
- **Access control (in RAG)**: Enforcing which knowledge sources or documents a given user is permitted to have retrieved for them, applied before or during retrieval, not just at the UI layer.
- **Citation & provenance**: Attaching sources to claims in a generated answer, so a human can verify the claim against its origin.
- **Agentic RAG**: An agent-based RAG implementation, where an agent can plan, reason, and decide whether and how to use RAG as one tool among several, rather than always retrieving the same fixed way. Covered in depth next class, alongside multi-agent systems and RAG evaluation.
