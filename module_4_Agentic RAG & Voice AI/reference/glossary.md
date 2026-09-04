# Glossary (Source of Truth)

Master list of terms for this module. `study-material/key-concepts.md` repeats the subset most relevant to the lesson itself; this file is the fuller reference.

## Agentic RAG

- **Agentic RAG**: Agent-based RAG implementation. Utilizes intelligent agents that can plan, reason, and learn over time. RAG becomes just one tool an agent can decide to use, agents can decide to use RAG together with other tools.
- **Routing**: The simplest form of agentic reasoning, uses an LLM to pick the downstream RAG pipeline (e.g. choosing between a Summary Query Engine and a Vector Query Engine as tools).
- **One-Shot Query Planning**: Breaks a query down into parallelizable sub-queries. Each sub-query can be executed against any set of RAG pipelines. Once the sub-query results are generated, they are synthesized into a final response. An LLM is used to decompose the input query into sub-queries and call the appropriate RAG query engine; the individual sub-responses are then synthesized to generate the final output based on the agent's instructions.
- **Tool Use**: Using an LLM to call an API and infer the parameters of that API. The LLM generates the arguments/parameters for the external API or SQL statement from the input query; a tool makes the call to an external API, database, etc., and the agent synthesizes the final response based on the agent's instructions and output parsers, if any.
- **Conversation Memory**: A flat list of the conversations the agent had with the user. The agent reasoning loop fetches conversation history before responding and stores conversation history after each turn, alongside handling tool input/output.
- **Agent ingredients vs. full agents spectrum**: Routing, Tool Use, One-Shot Query Planning, and Conversation Memory are "Agent Ingredients" — simple, lower cost, lower latency. ReAct and Dynamic Planning + Execution are "Full Agents" — advanced, higher cost, higher latency.
- **ReAct**: A full-agent pattern (named on the "Full Agents" side of the agent-ingredients spectrum, alongside Dynamic Planning + Execution) that goes beyond the simpler agent ingredients (routing, tool use, one-shot query planning, conversation memory).

## Voice AI

- **Voice AI**: Described as becoming the new interface, with enterprise-ready voice agents for automated phone calls, customer conversations, and inbound/outbound call handling now offered across many vendor products.
- **Speech-to-Speech (S2S)**: A one-hop pipeline: user speech goes into a single Speech-to-Speech model (audio in -> audio out, natively) and comes out as agent speech. Same underlying core as a standard text LLM (decoder-only transformer), but input is audio encoded to audio tokens, the token stream is unified across audio/text/image/video, and output is audio tokens decoded to streaming audio, with tool calls possible mid-turn and an optional text transcript.
- **Cascaded (STT -> LLM -> TTS)**: A three-hop pipeline: Speech-to-Text (STT/ASR) converts user speech to text, an LLM reasons over the text and generates a text response, and Text-to-Speech (TTS) converts that response back to audio. Three discrete, independently swappable models chained together, with text at every boundary; each stage (accuracy, cost, language, voice) can be picked independently.
- **STT / ASR (Speech-to-Text / Automatic Speech Recognition)**: The stage that transcribes user audio into text in a cascaded pipeline.
- **TTS (Text-to-Speech)**: The stage that converts text back into natural-sounding audio in a cascaded pipeline.
- **Full-duplex**: Audio can flow in both directions (listening and speaking) at the same time, like a real phone call.
- **VAD (Voice Activity Detection)**: Detects when a person is actually speaking vs. silence/background noise, used to know when to start/stop listening.
- **Barge-in**: When a user starts talking while the model is still speaking, and the system detects it and stops/flushes its own audio output to let the user interrupt naturally.
- **WebRTC (Web Real-Time Communication)**: Open browser standard for streaming audio/video in real time, low latency, no plugins needed.
- **SIP (Session Initiation Protocol)**: Signaling protocol used by phone systems to set up and manage calls. Bridges voice agents to real phone numbers and carriers.

## Voice AI architecture trade-offs

- **S2S trade-off, in short**: Fast and natural, less control. Lower latency (~200-400ms), hears emotion/tone/pace natively, better barge-in handling, simpler architecture (one API, one vendor), no transcription errors corrupting LLM input, no context lost between pipeline handoffs — versus voice quality below dedicated TTS (no custom/cloned voices), no transcripts by default, weak tool use, lower STT accuracy on accents/jargon, only 3-4 real model options, expensive audio tokens, locked to the model's built-in voice/behavior, and hard to observe or debug.
- **Cascaded trade-off, in short**: More control, more latency. Any voice (custom, cloned, brand voice), best-in-class STT accuracy, full conversation transcripts out of the box, easy tool calls/RAG/mid-pipeline guardrails, dozens of provider combos, cheaper at scale, independently swappable components, observable at every step — versus higher latency (three sequential handoffs, ~500-800ms), more moving parts, context that can be lost or distorted between STT -> LLM -> TTS, transcription errors that propagate to the LLM, less natural turn-taking with batch STT, three vendor relationships/three bills, extra engineering for barge-in, and lost emotion/tone once audio becomes text.
- **Open-source S2S maturity (as of this module)**: Still immature across every option — e.g. a most-capable open S2S model with no orchestration-framework plugin, a strongest on-paper agentic voice model gated behind early access requiring large GPUs, open-weight models whose realtime "Talker" only ships through a closed hosted API, an older-generation model with no tool support, and only one open S2S model with an official orchestration-framework plugin (self-hostable on a single GPU) but with no function calling, transcripts, or conversation memory.
- **Open-source cascaded coverage**: Open-source models now exist for every cascade stage: open TTS models, open STT/ASR models, and open LLMs, so a fully open-source cascaded pipeline is achievable even where open-source S2S is not yet mature.

## Voice AI frameworks and stack

- **Voice stack, four layers**: Layer 1 Transport/Media (real-time audio streams: WebRTC, WebSocket, SIP; jitter and echo cancellation), Layer 2 Intelligence (STT -> LLM -> TTS, or a single Speech-to-Speech model), Layer 3 Orchestration (turn-taking, barge-in, VAD, state, and latency budgeting), Layer 4 Reasoning (optional; a general agent framework for memory, multi-step workflows, and tools). The "which framework" question is ultimately about who owns these layers and how freely you can swap each block.
- **Model-Agnostic Orchestrators**: Build-it-yourself frameworks that own timing and integration, allowing you to bring your own models. Also open-source. Examples named in this module: LiveKit Agents, Pipecat. For teams that need control over latency, cost, model choice, or self-hosted deployment.
- **Full-Stack Managed Platforms**: Hosted and configured; bundle telephony, orchestration, and models behind a managed API. Also closed-source. Examples named in this module: ElevenLabs, Vapi. For teams that want to move fast without managing infrastructure.
- **ElevenAgents**: A no-code, fully managed voice agent platform with browsable templates, for simple use cases where users don't even need to set up an agent development kit (ADK) agent.

## RAG evaluation (recap and extension)

- **The Five Pillars of Evaluation (hierarchy of capability)**: A pyramid, Level 1 LLM Quality + Efficiency Evals, Level 2 Reasoning Evals, Level 3 Retrieval Evals, Level 4 Generation Evals, Level 5 Agent Evals — grouped into three domains: Domain 1 The LLM Core (Levels 1-2), Domain 2 The RAG Engine (Levels 3-4), Domain 3 The Agent Interface (Level 5).
- **Level 3, Knowledge Access / Retrieval Evals**: Core question: can the system find the right information efficiently? Measures the performance of the retrieval system that feeds context to the LLM: relevance, recall, and precision of the sources it cites. A powerful reasoning engine is useless if it operates on flawed or incomplete information.
- **BEIR (Benchmarking-IR)**: A diverse collection of information retrieval tasks, used as a common benchmark dataset for retrieval evaluation.
- **MS MARCO**: A large-scale dataset for passage ranking and reading comprehension, used as a common benchmark dataset for retrieval evaluation.
- **Natural Questions (NQ)**: Queries from real Google search users, requiring systems to find answers in Wikipedia articles; used as a common benchmark dataset for retrieval evaluation.
- **NDCG@k (Normalized Discounted Cumulative Gain)**: Measures ranking quality, rewarding highly relevant documents placed at the top.
- **Recall@k**: What percentage of all relevant documents were found in the top "k" results.
- **Precision@k**: Of the top "k" documents retrieved, what percentage were relevant.
- **Mean Reciprocal Rank (MRR)**: Measures the rank of the first correct answer.
- **Level 4, Grounded Generation / Generation Evals**: Core question: is the final answer grounded in the retrieved documents? The critical test to ensure the LLM isn't hallucinating or "freelancing" with its creativity; verifies the output is a faithful synthesis of the provided context. Core challenge: preventing hallucination.
- **Faithfulness**: Does the generated answer directly follow from the provided context? A direct measure against hallucination. Also described as: response stays within retrieved context.
- **Answer Relevancy**: Is the answer relevant to the user's original query?
- **Context Precision**: Is the retrieved context necessary and concise for answering the query (signal-to-noise ratio)?
- **Context Recall**: Did the retriever find all the necessary information from the knowledge base to answer the query completely?
- **Groundedness**: Claims in the generated response are supported by the source data.
- **Hallucination Rate**: The frequency of unsupported outputs.
- **Completeness**: Whether the generated response covers all aspects of the query.
