# Module 4: Quiz

## Q1. What does "Agentic RAG" mean, and what is the key reframe it makes about RAG itself?
- Type: recall
- **Answer:** Agentic RAG is an agent-based RAG implementation, it utilizes intelligent agents that can plan, reason, and learn over time. The key reframe: RAG is just one tool, agents can decide to use RAG together with other tools, rather than every query always going through the same fixed retrieval path.
- **Hint:** In the module's own diagram, what sits above the RAG box, deciding whether and how to use it?

## Q2. Name the four "Agent Ingredients" from the agent-ingredients-to-full-agents spectrum, and where they sit on the cost/latency scale relative to "Full Agents."
- Type: recall
- **Answer:** Routing, One-Shot Query Planning, Tool Use, and Conversation Memory. They sit on the simple, lower-cost, lower-latency side of the spectrum, versus "Full Agents" (ReAct, Dynamic Planning + Execution), which are advanced, higher-cost, higher-latency.
- **Hint:** The module draws this as a single horizontal spectrum with two labeled ends.

## Q3. A query needs to be answered by picking between a Summary Query Engine and a Vector Query Engine, with no query decomposition involved. Which Agentic RAG ingredient is this, and what decides which engine gets picked?
- Type: application
- **Answer:** Routing, the simplest form of agentic reasoning. An LLM (the Router) is used to pick the downstream RAG pipeline/tool.
- **Hint:** Is the query being split into pieces here, or just directed whole to one of two destinations?

## Q4. Walk through what One-Shot Query Planning does with a comparison query like "Compare candidate A's and B's open-source contributions," step by step.
- Type: explain-why
- **Answer:** The query is broken down into parallelizable sub-queries (e.g. "Describe A's contributions," "Describe B's contributions"). Each sub-query is executed against a RAG pipeline (an LLM decomposes the query and calls the appropriate RAG query engine for each sub-query). Once the sub-query results come back, they are synthesized into one final response, based on the agent's instructions.
- **Hint:** How many times does retrieval happen here, once for the whole blended query, or once per sub-question?

## Q5. In the Conversation Memory diagram, what specifically gets fetched and what gets stored on every new message?
- Type: recall
- **Answer:** On a new chat message, the agent reasoning loop fetches conversation history from storage; it may also send tool input and receive tool output as part of handling the message. After responding, it stores the (updated) conversation history back. The memory itself is just a flat list of the conversations the agent had with the user.
- **Hint:** Look at the two arrows between the "Agent Reasoning Loop" and "Conversation History" in the diagram, they point in opposite directions and are labeled differently.

## Q6. Name the two fundamental voice AI architectures from this module, and how many "hops" each one has.
- Type: recall
- **Answer:** Speech-to-Speech (S2S), one hop (a single model, audio in, audio out, natively), and Cascaded (STT → LLM → TTS), three hops (Speech-to-Text, then the LLM, then Text-to-Speech, as three separate stages).
- **Hint:** The module's own slide title for this pairs one architecture with "speed" and the other with "control."

## Q7. How does an S2S model's transformer core compare to a standard text LLM's, and what specifically is different about it?
- Type: explain-why
- **Answer:** They share the same core, a decoder-only transformer. What differs is the modality: an S2S model's input is audio encoded into audio tokens (vs. text tokens), its token stream is unified across audio/text/image/video (vs. text-only), and its output is audio tokens decoded to streaming PCM audio delivered full-duplex with VAD and barge-in (vs. detokenized text delivered as a batch or text stream).
- **Hint:** The comparison table in the lesson has a row explicitly labeled "same core," what's in that row for both columns?

## Q8. List three pros and three cons of the Cascaded (STT → LLM → TTS) architecture, according to the module's pros/cons table.
- Type: recall
- **Answer:** Pros (pick any three): any/custom/cloned voice, best-in-class STT accuracy, full conversation transcripts out of the box, easy tool calls/RAG/guardrails, dozens of provider combos, cheaper at scale, independently swappable components, observable at every step. Cons (pick any three): higher latency (three sequential handoffs, ~500-800ms), more moving parts, context can be lost/distorted between stages, transcription errors propagate to the LLM, less natural turn-taking with batch STT, three vendor relationships/bills, extra engineering for barge-in, emotion/tone lost when audio becomes text.
- **Hint:** This is a straight recall from the "Cascaded: more control, more latency" table.

## Q9. According to the "Cheaper architecture depends on the provider" comparison, is S2S always cheaper, always more expensive, or does it depend? Give the specific numbers for one provider as evidence.
- Type: explain-why
- **Answer:** It depends on the provider, there's no universal winner. For Google, S2S is ~27% cheaper ($0.0119 vs. $0.0164 cascaded per turn). For OpenAI, Cascaded is ~59% cheaper ($0.0101 vs. $0.0246 S2S per turn). For xAI, Cascaded is ~90% cheaper ($0.0049 vs. $0.0500 S2S per turn).
- **Hint:** Do all three providers in that table point the same direction, or do they split?

## Q10. What are the four layers of the voice stack, from the bottom up, and what does each one own?
- Type: recall
- **Answer:** Layer 1, Transport/Media: real-time audio streams (WebRTC, WebSocket, SIP), jitter, and echo cancellation. Layer 2, Intelligence: STT → LLM → TTS, or a single S2S model. Layer 3, Orchestration: turn-taking, barge-in, VAD, state, and latency budgeting. Layer 4, Reasoning (optional): a general agent framework for memory, multi-step workflows, and tools.
- **Hint:** The module frames the "which framework" question as really being about who owns these four layers.

## Q11. What's the core difference between a "Model-Agnostic Orchestrator" and a "Full-Stack Managed Platform," and name one example of each from the module.
- Type: application
- **Answer:** A Model-Agnostic Orchestrator is a build-it-yourself, open-source framework that owns timing and integration but lets you bring your own models, e.g. LiveKit Agents or Pipecat, for teams that need control over latency, cost, model choice, or self-hosted deployment. A Full-Stack Managed Platform is a hosted, closed-source, bundled telephony + orchestration + models package behind one managed API, e.g. ElevenLabs or Vapi, for teams that want to move fast without managing infrastructure.
- **Hint:** One category's examples are self-hostable with a "$0 self-hosted" platform cost; the other's are "Managed SaaS" with a per-minute platform cost.

## Q12. A team needs self-hosted deployment, SIP/telephony support, and 20+ STT providers. Which framework from the "Managed for speed, open-source for control" table fits all three, and which framework almost fits but falls short on one of them?
- Type: application
- **Answer:** Pipecat fits all three (self-hostable: yes; SIP/telephony: yes, cloud only; STT: 20+ providers). LiveKit Agents almost fits, it is self-hostable and supports SIP/telephony, but only offers "3+ via plugins" for STT, short of the 20+ requirement.
- **Hint:** Compare the "Self-hostable," "SIP / telephony," and "STT" rows across all four columns.

## Q13. In the Five Pillars of Evaluation, which level is "Retrieval Evals," what's its core question, and name two of its key performance metrics.
- Type: recall
- **Answer:** Level 3, part of Domain 2 (The RAG Engine). Core question: can the system find the right information efficiently? Key performance metrics (any two): NDCG@k, Recall@k, Precision@k, Mean Reciprocal Rank (MRR).
- **Hint:** This is the level right below "Generation Evals" in the pyramid.

## Q14. What is the "core challenge" of Level 4, Grounded Generation, and name two metrics used to measure it.
- Type: recall
- **Answer:** Core challenge: preventing hallucination, verifying the output is a faithful synthesis of the provided context rather than the LLM "freelancing." Metrics (any two): Faithfulness, Answer Relevancy, Context Precision, Context Recall (or, on the generation-quality side specifically: Faithfulness, Groundedness, Hallucination Rate, Completeness).
- **Hint:** The module states this level's core question and core challenge as two separate, explicit lines.
