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

## RAG evaluation

- **The Five Pillars of Evaluation (hierarchy of capability)**: A pyramid, Level 1 LLM Quality + Efficiency Evals, Level 2 Reasoning Evals, Level 3 Retrieval Evals, Level 4 Generation Evals, Level 5 Agent Evals — grouped into three domains: Domain 1 The LLM Core (Levels 1-2), Domain 2 The RAG Engine (Levels 3-4), Domain 3 The Agent Interface (Level 5).
- **The core question at each level**: Level 1, is the underlying model good, cheap, and fast enough to build on? Level 2, can the model reason over what it is given? Level 3, can the system find the right information efficiently? Level 4, is the final answer grounded in the retrieved documents? Level 5, does the agent accomplish the task it was given? Each level assumes the one beneath it already works, which is why a Level 5 agent failure is often a Level 3 retrieval failure in disguise.
- **Level 3, Knowledge Access / Retrieval Evals**: Core question: can the system find the right information efficiently? Measures the performance of the retrieval system that feeds context to the LLM: relevance, recall, and precision of the sources it cites. A powerful reasoning engine is useless if it operates on flawed or incomplete information.
- **BEIR (Benchmarking-IR)**: A diverse collection of information retrieval tasks, used as a common benchmark dataset for retrieval evaluation.
- **MS MARCO**: A large-scale dataset for passage ranking and reading comprehension, used as a common benchmark dataset for retrieval evaluation.
- **Natural Questions (NQ)**: Queries from real Google search users, requiring systems to find answers in Wikipedia articles; used as a common benchmark dataset for retrieval evaluation.
- **NDCG@k (Normalized Discounted Cumulative Gain)**: Measures ranking quality, rewarding highly relevant documents placed at the top.
- **Recall@k**: What percentage of all relevant documents were found in the top "k" results.
- **Precision@k**: Of the top "k" documents retrieved, what percentage were relevant.
- **Mean Reciprocal Rank (MRR)**: Measures the rank of the first correct answer.
- **What each retrieval metric is sensitive to**: NDCG@k -> order (a relevant document at rank 10 scores worse than the same document at rank 1); Recall@k -> completeness (did you miss anything relevant, anywhere in the top k); Precision@k -> cleanliness (how much of what you retrieved was useful); MRR -> how fast the first right answer shows up. They disagree on purpose, pick the one matching the failure you have.
- **Level 4, Grounded Generation / Generation Evals**: Core question: is the final answer grounded in the retrieved documents? The critical test to ensure the LLM isn't hallucinating or "freelancing" with its creativity; verifies the output is a faithful synthesis of the provided context. Core challenge: preventing hallucination.
- **Faithfulness**: Does the generated answer directly follow from the provided context? A direct measure against hallucination. Also described as: response stays within retrieved context.
- **Answer Relevancy**: Is the answer relevant to the user's original query?
- **Context Precision**: Is the retrieved context necessary and concise for answering the query (signal-to-noise ratio)?
- **Context Recall**: Did the retriever find all the necessary information from the knowledge base to answer the query completely?
- **Groundedness**: Claims in the generated response are supported by the source data.
- **Hallucination Rate**: The frequency of unsupported outputs.
- **Completeness**: Whether the generated response covers all aspects of the query.
- **The two halves of a RAG answer**: Context Precision and Context Recall measure the *retrieval* half (do you even have the right material); Faithfulness, Groundedness, Hallucination Rate, and Completeness measure the *generation* half (given that material, did the model use it correctly and fully). A RAG system can fail at either half independently, so the diagnostic habit is to inspect the retrieved context before judging the answer.
- **Reranking's reach**: A reranker changes the *order* of retrieved results but not their membership, so it can only move NDCG@k and MRR. Recall@k is unaffected, if a relevant document never made the top k at all, reranking cannot recover it, that is an upstream chunking, embedding, or retrieval-depth problem.
- **Diagnostic order**: Read the retrieved context before judging the answer. If the material needed to answer isn't in it, you have a Context Recall problem and every generation metric is misleading, the model was never given a chance. The trap this avoids is tuning prompts to fix what is actually a retrieval bug.
