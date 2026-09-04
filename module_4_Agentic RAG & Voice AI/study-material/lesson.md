# Module 4: Agentic RAG & Voice AI

## Learning outcomes for Module 4

By the end of this module you can:

- Explain Naive RAG and its pain points (recap from Module 3)
- Describe what Agentic RAG is
- Explain routing, decomposition (one-shot query planning), and semantic caching
- Compare Naive RAG vs. Agentic RAG
- Understand Voice AI architectures: Speech-to-Speech (S2S) and Cascaded (STT -> LLM -> TTS)

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

## Concept 7: Voice AI Architectures

Voice AI is becoming **the new interface**: enterprise-ready voice AI agents for automated phone calls, voice AI for regulated industries, speaking human to every customer, AI call centers, and AI voice agents for handling inbound calls are now offered widely across the vendor landscape.

**Two architectures: S2S for speed, Cascaded for control.** There are two fundamental approaches: a direct **Speech-to-Speech (1 hop)** pipeline for low latency, and a **Cascading (3 hops)** pipeline that trades speed for flexibility and control.

```
Speech-to-Speech — 1 hop
User Speech -> [Speech-to-Speech Model: audio in -> audio out, natively] -> Agent Speech

Cascaded — 3 hops
User Speech -> [STT: speech -> text] -> [LLM: understand + respond] -> [TTS: text -> speech] -> Agent Speech
```

**How an S2S model differs from an LLM.** Both a standard text LLM (GPT, Claude, Llama, Gemini) and an S2S model (gpt-realtime, Gemini Live, native audio) share the **same core**: a decoder-only transformer. What differs: input (text vs. audio encoded to audio tokens), the token stream (text-only vs. unified audio+text+image+video), and output (text tokens vs. audio tokens decoded to 24kHz PCM, delivered as full-duplex streaming with VAD and barge-in over WebSocket, vs. a detokenized text response).

**One transformer, full-duplex, native barge-in.** The model layer (native audio, multimodal): audio encoded into tokens, mixed with text/image/video in one stream; a single transformer reasons across all modalities together; generates output audio tokens directly, no separate TTS step; an optional parallel text transcript is the only way to get text out; streams in/out over a full-duplex WebSocket with built-in VAD and barge-in; tool calling still works mid-turn.

**Comparing closed-source S2S models:**

| Provider | Model | Cost (input) | Cost (output) | Latency |
|---|---|---|---|---|
| Google | gemini-3.1-flash-live-preview | $3.00/M audio tok (~$0.005/min) | $12.00/M audio tok (~$0.018/min) | ~960ms-2.98s |
| OpenAI | gpt-realtime-2.1-mini | $10.00/M audio tok / $0.60/M text tok | $20.00/M audio tok / $2.40/M text tok | ~500ms |
| xAI | Grok Voice Agent API | $0.05/minute (all-in) | — (single flat rate) | <1s time-to-first-audio |

**Open-source S2S is still immature across every option** — see `../reference/voice-ai-architectures.md` for the five specific models named and why each falls short (missing plugins, gated weights, closed hosted realtime layers, no tool support, or missing function calling/transcripts/memory).

**S2S pros/cons, at a glance:** lower latency, native emotion/tone/pace, better barge-in, simpler one-vendor architecture, no transcription errors, no lost context between handoffs — versus below-dedicated-TTS voice quality, no transcripts by default, weak tool use, lower STT accuracy on accents/jargon, few model options, expensive audio tokens, and being hard to observe or debug.

**Cascaded: three swappable, tunable stages.** Three discrete, independently swappable models chained with text at every boundary: Audio Input -> Speech-to-Text (STT/ASR) -> LLM Reasoning -> Text Response -> Text-to-Speech (TTS) -> Agent Speech, in a continuous conversation loop. You pick each stage independently (accuracy, cost, language, voice).

**Comparing closed-source cascaded models:**

| Provider | STT | LLM | TTS | Cumulative Cost (input) | Cumulative Cost (output) | Cumulative Latency |
|---|---|---|---|---|---|---|
| Google | gemini-3.1-flash-lite | gemini-2.5-flash | gemini-3.1-flash-tts-preview | $1.80/M tok | $24.00/M tok | ~1.5-3s+ |
| OpenAI | gpt-4o-mini-transcribe | gpt-5.4-mini | gpt-4o-mini-tts | $2.60/M tok | $21.50/M tok | ~1.5-3s |
| xAI | Grok Speech-to-Text | Grok 4.3 | Grok Text-to-Speech | $16.25/M tok | $2.50/M tok + streaming/hr | Not officially published |

**Cascaded pros/cons, at a glance:** any/custom/cloned voice, best-in-class STT accuracy, full transcripts, easy tool calls/RAG/guardrails, dozens of provider combos, cheaper at scale, independently swappable, observable — versus higher latency (3 sequential handoffs), more moving parts, context loss between stages, transcription errors propagating to the LLM, less natural turn-taking, three vendor relationships/bills, extra barge-in engineering, and lost emotion/tone.

**Open-source now covers every cascade stage:** open TTS (Fish Audio S2 Pro, Step Audio EditX, Voxtral TTS), open STT/ASR (Nemotron 3 ASR, Voxtral Mini/Realtime, Qwen3-ASR-1.7B), and open LLMs (GLM-5.2, DeepSeek V4 Pro, Kimi K2.6/K2.7).

**NVIDIA and Soniox win cheap-and-fast** on the price-vs-latency quadrant of cascaded STT+TTS combinations (NVIDIA ~$0.15/hr at ~300ms; Soniox ~$0.82/hr at ~350ms), while Google and OpenAI land in the "slow & pricey, avoid" quadrant, and ElevenLabs is fast but premium-priced.

**S2S wins speed; Cascaded wins flexibility**, across latency, naturalness, cost (which flips by provider, see `../reference/voice-ai-architectures.md`), debuggability, flexibility/lock-in, and current (2026) enterprise adoption, where cascaded still dominates production deployments for control, cost, and compliance while S2S adoption is emerging where latency and naturalness dominate.

**Choosing between them:** Choose S2S when latency is the top priority, emotional context matters, the agent is a simple conversational one with no complex tool use, natural interruption is critical, infrastructure should be minimal, or the conversation is short and self-contained. Choose Cascaded when you need a specific/cloned/brand voice, high STT accuracy, full transcripts for compliance, structured tool calls/RAG/guardrails, cost sensitivity at scale, or provider flexibility.

---

## Concept 8: Voice AI Frameworks

**The voice landscape** spans an Application Layer (vertical products across Call Center, Customer Service/Support, Restaurant/Hospitality, Emergency Response, Finance/Banks, Home Services, Real Estate, Insurance, Logistics/Fleet, Medical, Sales, and Recruiting) built on an Infrastructure Layer (Voice to Voice, Voice Eval and Testing, Voice Middleware, ASR, TTS, and LLMs/SLMs).

**Debunking the voice stack, four layers:**

```
Layer 4: Reasoning (Optional)   — General agent framework (e.g. LangGraph) for memory, multi-step workflows, and tools.
Layer 3: Orchestration          — Turn-taking, barge-in, VAD, state, and latency budgeting.
Layer 2: Intelligence           — STT -> LLM -> TTS, or a single Speech-to-Speech (S2S) model.
Layer 1: Transport / Media      — Real-time audio streams (WebRTC, WebSocket, SIP), jitter, and echo cancellation.
```

The "which framework" question is ultimately about **who owns these layers and how freely you can swap each block**.

**Two categories of framework:**

1. **Model-Agnostic Orchestrators** (also Open-Source): Build it yourself. Frameworks that own timing and integration, allowing you to bring your own models. Examples: **LiveKit Agents**, **Pipecat**. For teams that need control over latency, cost, model choice, or self-hosted deployment.
2. **Full-Stack Managed Platforms** (also Closed-Source): Hosted and configured. Bundled telephony, orchestration, and models behind a managed API. Examples: **ElevenLabs**, **Vapi**. For teams that want to move fast without managing infrastructure.

**ElevenAgents: no-code templates.** For simple use cases, users don't even need to set up an ADK agent and can use fully managed voice agent platforms with browsable templates.

**Live demo: Iris (Traversaal.ai's Customer Support Agent).** URL: `https://traversaal-iris.vercel.app/`. Modeled as a workflow: Start -> Initial Inquiry -> (the caller's primary interest has been identified) -> Provide Information & Next Steps -> (the agent has provided all relevant info) -> Wrap Up.

**Managed for speed, open-source for control:**

| | Vapi | ElevenLabs | LiveKit Agents | Pipecat |
|---|---|---|---|---|
| Type | Managed SaaS | Managed SaaS | Open-source | Open-source |
| Platform cost/min | $0.05 + providers | $0.08 bundled | $0 self-hosted | $0 self-hosted |
| Free tier | 60+ min/mo | 15 min/mo | 1,000 min/mo | WebRTC free |
| STT | 6+ providers (BYOK) | Own Scribe v2 only | 3+ via plugins | 20+ providers |
| LLM | 10+ providers | 10+ (BYO endpoint) | Any | Any (20+) |
| Self-hostable | ✗ | ✗ | ✓ | ✓ |
| SIP / telephony | ✓ | ✓ | ✓ | ✓ Cloud only |
| Website embed | Widget + SDK | Widget (easiest) | WebRTC SDK | DIY only |
| Lock-in | Low-Medium | High | Very Low | Very Low |
| Best for | BYOK + flexibility | Best voice quality | Scale + cost | Custom pipelines |

---

## Key Takeaways

1. Cascading pipeline **performs better** than S2S for complicated scenarios.
2. Cascading pipeline gives us an option to explore **open source alternatives**, which reduces overall cost.
3. The **latency** of an S2S model varies on a case-to-case basis, and outperforms cascaded pipeline.
4. S2S maintains better **tone** and **context**.
5. There exist **managed serverless voice agent platforms** for teams who want simpler solutions and don't want to manage the infrastructure.
6. **Framework selection** for voice agents highly depends on user requirements. Certain open-source frameworks such as LiveKit and Pipecat provide support for all types of models, whereas SDKs such as Google ADK and OpenAI SDK, etc., have restricted support on voice models by other vendors.
7. While selecting a framework, it is recommended to ensure that the selected framework provides **built-in transport layer** and **SIP support** for a seamless voice experience.

---

## Appendix: Key terms to remember

- **Full-duplex**: Audio can flow in both directions (listening and speaking) at the same time, like a real phone call.
- **VAD (Voice Activity Detection)**: Detects when a person is actually speaking vs. silence/background noise, used to know when to start/stop listening.
- **Barge-in**: When a user starts talking while the model is still speaking, and the system detects it and stops/flushes its own audio output to let the user interrupt naturally.
- **WebRTC (Web Real-Time Communication)**: Open browser standard for streaming audio/video in real time, low latency, no plugins needed.
- **SIP (Session Initiation Protocol)**: Signaling protocol used by phone systems to set up and manage calls. Bridges voice agents to real phone numbers and carriers.

## Appendix: Evaluating RAG

**Recap — a hierarchy of capability, the Five Pillars of Evaluation:** Level 5 Agent Evals, Level 4 Generation Evals, Level 3 Retrieval Evals, Level 2 Reasoning Evals, Level 1 LLM Quality + Efficiency Evals, grouped as Domain 3 The Agent Interface (Level 5), Domain 2 The RAG Engine (Levels 3-4, this module's Appendix focus), and Domain 1 The LLM Core (Levels 1-2).

**Level 3: Knowledge Access.** Core question: Can the system find the right information efficiently? Measures relevance, recall, and precision of the sources cited. Common benchmark datasets: BEIR (Benchmarking-IR), MS MARCO, Natural Questions (NQ). Key performance metrics: NDCG@k, Recall@k, Precision@k, Mean Reciprocal Rank (MRR).

**Level 4: Grounded Generation.** Core question: Is the final answer grounded in the retrieved documents? Core challenge: preventing hallucination. Metrics: Faithfulness, Answer Relevancy, Context Precision, Context Recall — and, on the generation-quality side specifically: Faithfulness (response stays within retrieved context), Groundedness (claims are supported by source data), Hallucination Rate (frequency of unsupported outputs), Completeness (covers all aspects of the query).

See `../reference/rag-evaluation.md` for the full deep dive on both levels.

## Summary

1. Naive RAG's Ingestion/Retrieval/Generation pipeline, chunking strategies, and pain points (summarize, comparison, implicit/multi-hop, memory) carry over from Module 3, and Enterprise RAG's stages address them.
2. Agentic RAG treats RAG as one tool an agent can choose to use. Four "agent ingredients" — Routing, One-Shot Query Planning, Tool Use, Conversation Memory — sit on the simple/cheap/low-latency end of a spectrum that runs up to "Full Agents" (ReAct, Dynamic Planning + Execution).
3. Voice AI has two fundamental architectures: Speech-to-Speech (one hop, faster, less control) and Cascaded (STT -> LLM -> TTS, three hops, more control, more latency). Which one wins on cost and latency depends on the provider, not the architecture alone.
4. A voice stack has four layers (Transport/Media, Intelligence, Orchestration, and optional Reasoning). Frameworks split into Model-Agnostic Orchestrators (LiveKit Agents, Pipecat) and Full-Stack Managed Platforms (ElevenLabs, Vapi), trading control for speed of setup.
5. RAG evaluation's Five Pillars pyramid groups into three domains; this module's Appendix goes deep on Domain 2, The RAG Engine: Level 3 Retrieval Evals (relevance, recall, precision; BEIR/MS MARCO/NQ; NDCG@k, Recall@k, Precision@k, MRR) and Level 4 Generation Evals (faithfulness, groundedness, hallucination rate, completeness).

## Where to next

Do `exercises.md` for hands-on practice with agentic RAG design and voice architecture selection. Or ask to be quizzed (`quiz.md`). Week 5 covers **Voice Agents & Conversational Interfaces** in more depth, building on the S2S/Cascaded architecture choice and framework landscape introduced here.
