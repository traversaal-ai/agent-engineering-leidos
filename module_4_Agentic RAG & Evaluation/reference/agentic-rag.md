# Reference: Agentic RAG

Deep dive on the module's "Introduction to Agentic RAG" section. Picks up exactly where Module 3 left off: naive RAG retrieves once, and Enterprise RAG's Agentic Router picks a knowledge base once, up front, neither one lets an agent decide to retrieve *again* based on what it just found.

## Recap: where Module 3 stopped

Module 3 covered Naive RAG (the three-stage pipeline: Ingestion, Retrieval, Generation), its four specific pain points (struggles to summarize, comparison is a headache, implicit data / multi-hop reasoning, no memory), and Enterprise RAG (guardrails, semantic cache, query rewriter, agentic router with access control, citation & provenance, monitoring) as the fix. This module's recap slide names the same four items: Naive RAG & Enterprise RAG, what chunking is and why it's needed, the different chunking strategies, and Naive RAG's pain points.

## What is Agentic RAG?

**Agentic RAG = Agent-based RAG implementation.** Agentic RAG utilizes intelligent agents that can plan, reason, and learn over time.

```
Query -> Agents? -> RAG -> Agents? -> Response
              ^
          Agents?
```

The key reframe: **RAG is just one tool.** Agents can decide to use RAG together with other tools, rather than RAG being the fixed, only path a query takes.

## The spectrum: agent ingredients to full agents

```
Agent Ingredients                          |  Full Agents
Routing                    Tool Use        |  ReAct        Dynamic Planning
One-Shot Query Planning                    |               + Execution
Conversation Memory                        |
------------------------------------------------------------------------->
Simple, Lower Cost, Lower Latency          |  Advanced, Higher Cost, Higher Latency
```

Four "agent ingredients" sit on the simpler, cheaper, lower-latency side of the spectrum: Routing, One-Shot Query Planning, Tool Use, and Conversation Memory. "Full Agents," ReAct and Dynamic Planning + Execution, sit on the advanced, higher-cost, higher-latency side. The four ingredients below are the building blocks; a full agent combines and extends them.

## Routing

**Simplest form** of agentic reasoning that uses an LLM to pick the downstream RAG pipeline.

```
Query -> [Router] <--> [Tools: RAG Summary Query Engine, RAG Vector Query Engine] -> Response
              ^                        |
              |________________________|
                    (via LLM, e.g. OpenAI GPT)
```

The router sits inside the agent, consults an LLM to decide, and picks between the available tools, here, two different RAG query engines, a Summary Query Engine and a Vector Query Engine, rather than always using the same one.

## One-Shot Query Planning

Break down a query into **parallelizable sub-queries**. Each sub-query can be executed against any set of RAG pipelines. Once the results of the sub-queries are generated, they are synthesized into a final response.

```
Query -> [Query Planner] <--> [Tools: RAG Query Engine A, RAG Query Engine B] -> [Synthesis] -> Response
              ^                                                                       ^
              |___________________ (via LLM, e.g. OpenAI GPT) ______________________|
```

An LLM decomposes the input query into sub-queries and calls the appropriate RAG query engine for each; the individual sub-responses are then synthesized to generate the final output, based on the agent's instructions. This is the direct fix for the "comparison is a headache" pain point from Module 3: instead of embedding a multi-part query as one blended vector, it's broken into sub-questions first, each retrieved separately, and only then combined.

## Tool Use

Use an **LLM to call an API and infer the parameters of that API**.

```
Query -> [Tools] <--> [Synthesizer] -> Response
             |
   {External API, SQL DB, Vector DB, Open Weather Map}
             ^
     (via LLM, e.g. OpenAI GPT)
```

An LLM is used to generate the arguments and parameters for the external API or SQL statement, from the input query. The tool then makes the call to the external API, database, etc., and the agent synthesizes the final response based on the agent's instructions and output parsers, if any. Note the examples of tools an agent can reach for here: an external API, a SQL DB, a Vector DB, and something like a weather API, RAG (the Vector DB) is one tool among several, exactly the reframe from "What is Agentic RAG?" above.

## Conversation Memory

The memory is just a **flat list of the conversations** the agent had with the user.

```
New Message (Chat) -> [Agent Reasoning Loop] <-> Conversation History (fetch / store)
                              |    ^
                     Tool Input   Tool Output
                              v    |
                        tool_1, tool_2, tool_3
```

Step by step: a new chat message comes in, the agent reasoning loop fetches conversation history, decides whether a tool is needed (sending tool input, e.g. to `tool_1`, and receiving tool output back), and stores the updated conversation history. This is the direct fix for the "no memory, disconnected dialogue" pain point from Module 3: because history is fetched and stored on every turn, a fact stated two turns ago is available when answering the current one.

## Demo: Naive RAG vs. Agentic RAG

The module includes a live, hands-on comparison of a Naive RAG pipeline against an Agentic RAG pipeline side by side, this is where the four ingredients above (routing, one-shot query planning, tool use, conversation memory) are meant to be seen actually changing the pipeline's behavior on the same queries that broke naive RAG in Module 3.

**Check:** Of the four naive RAG pain points from Module 3 (struggles to summarize, comparison is a headache, implicit data / multi-hop, no memory), which one maps most directly onto One-Shot Query Planning, and which one maps most directly onto Conversation Memory? Is there a pain point that One-Shot Query Planning (a *single* round of parallel sub-queries) still would not fully solve, one that would need the agent to look at what the first retrieval returned before deciding what to retrieve next? That question is exactly what separates the "Agent Ingredients" column from "Full Agents" (ReAct, Dynamic Planning + Execution) on the spectrum above.
