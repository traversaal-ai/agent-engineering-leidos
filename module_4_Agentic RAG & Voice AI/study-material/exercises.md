# Module 4: Exercises

No coding required for any of these. They use the module's own diagrams, pain-point examples, and comparison tables, no built app is required to do them.

## Exercise 1: Match the pain point to the agentic-RAG ingredient

**Goal:** Practice connecting Module 3's naive RAG pain points to the specific Agentic RAG ingredient that fixes each one.

**Steps:**
1. For each of Module 3's four naive RAG pain points (struggles to summarize, comparison is a headache, implicit data / multi-hop reasoning, no memory), name the single Agentic RAG ingredient from `reference/agentic-rag.md` (Routing, One-Shot Query Planning, Tool Use, Conversation Memory) most directly responsible for addressing it.
2. For "comparison is a headache" specifically, write out the two sub-questions One-Shot Query Planning would generate for the query "Compare candidate A's and B's open-source contributions."
3. Identify the one naive RAG pain point that none of the four ingredients fully solves on its own, the one that needs an agent to look at what a first retrieval returned before deciding what to retrieve next.

**Done when:** You have four pain-point-to-ingredient matches, the two sub-questions for the comparison example, and a one-sentence explanation of which pain point isn't fully solved and why (tie it to the "Agent Ingredients" vs. "Full Agents" spectrum).

## Exercise 2: Design a routing agent for your own knowledge bases

**Goal:** Apply the Routing ingredient to a set of RAG pipelines you actually understand.

**Steps:**
1. Name two or three distinct RAG "tools" (query engines) that could exist for your own team or organization, e.g. a Summary Query Engine over meeting notes and a Vector Query Engine over a technical wiki.
2. Write one realistic user query for each tool that the Router should send to that specific tool, and one sentence explaining what about the query signals which tool it needs.
3. Write one query that is ambiguous, plausibly answerable by either tool, and describe what information the Router (backed by an LLM) would need in the query to disambiguate it.

**Done when:** You have two or three tools, one matching query each, and one ambiguous query with your reasoning for how a router LLM would need to resolve it.

## Exercise 3: Pick S2S or Cascaded for five real scenarios

**Goal:** Practice using the "Choose S2S when... / Choose Cascaded when..." table from `reference/voice-ai-architectures.md` to make an actual architecture decision, not just recall the table.

**Steps:**
1. For each of the following five scenarios, pick S2S or Cascaded, and name the single row from the table that drove your decision: (a) a mental-health companionship app where tone and warmth matter most, (b) a medical intake line that must produce a full accurate transcript for the patient record, (c) a fast food drive-through order-taker with simple, short conversations, (d) a multi-lingual customer support line that needs to look up order status in a database mid-call, (e) a brand-voice marketing hotline that must sound exactly like the company's cloned spokesperson voice.
2. For scenario (d), explain specifically why "Structured tool calls... are needed" points to Cascaded, using what you know about S2S's "weak tool use" con from `reference/voice-ai-architectures.md`.

**Done when:** All five scenarios have a pick and a named justifying row, and (d)'s tool-use reasoning is written out in your own words.

## Exercise 4: Trace the cost/latency trade-off across providers

**Goal:** Internalize that "cheaper" and "faster" depend on the provider, not on the architecture name alone, using the module's own numbers.

**Steps:**
1. From the "Cheaper architecture depends on the provider" table (`reference/voice-ai-architectures.md`), write down which architecture wins for Google, OpenAI, and xAI, and by what percentage.
2. Explain in one or two sentences why a team that only read the general "S2S wins speed; Cascaded wins flexibility" table, without checking a specific provider's numbers, could end up making the wrong cost decision.
3. Using the closed-source S2S and cascaded comparison tables, name the provider with the lowest S2S latency, and the provider with the lowest cascaded cumulative cost (input).

**Done when:** You have the three providers' cost-winners with percentages, your one-to-two sentence explanation of the general-table pitfall, and the two provider names from step 3.

## Exercise 5: Choose a voice framework for a given team

**Goal:** Apply the "Managed for speed, open-source for control" comparison table (`reference/voice-ai-frameworks.md`) to a concrete team profile.

**Steps:**
1. A team needs: self-hosted deployment (no per-minute platform fee), SIP/telephony support, and access to 20+ STT providers. Using the table, name the one framework (of Vapi, ElevenLabs, LiveKit Agents, Pipecat) that satisfies all three requirements, and point to the specific row(s) that prove it.
2. A different team wants the fastest possible time-to-a-working-agent, doesn't want to manage any infrastructure, and cares most about voice quality. Name the framework that fits, and the row that justifies "voice quality" specifically.
3. For whichever framework you did **not** pick in step 1, name the one requirement from step 1 it fails on.

**Done when:** You have a framework pick with justification for both teams, and you've named the specific way the runner-up framework in step 1 falls short.
