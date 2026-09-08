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

## Q6. Name the five levels of the Five Pillars of Evaluation, and the three domains they group into.
- Type: recall
- **Answer:** Level 1 LLM Quality + Efficiency Evals, Level 2 Reasoning Evals, Level 3 Retrieval Evals, Level 4 Generation Evals, Level 5 Agent Evals. The domains: Domain 1, The LLM Core (Levels 1-2); Domain 2, The RAG Engine (Levels 3-4); Domain 3, The Agent Interface (Level 5).
- **Hint:** The module draws this as a pyramid with the domains labeled off to the right.

## Q7. Why is the Five Pillars model drawn as a pyramid rather than a flat checklist? Give a concrete consequence of that ordering.
- Type: explain-why
- **Answer:** Because each level assumes the one beneath it already works. Asking "did the model use its context faithfully?" (Level 4) is meaningless if the retriever handed it the wrong context in the first place (Level 3). The concrete consequence: a Level 5 agent failure is very often a Level 3 retrieval failure in disguise, so diagnosing at the wrong level sends you fixing the wrong part of the system.
- **Hint:** What has to already be true before a Level 4 score means anything at all?

## Q8. What is Level 3's core question, and what three properties of the retrieved sources does it measure? Name the three benchmark datasets the module lists.
- Type: recall
- **Answer:** Core question: can the system find the right information efficiently? It measures the **relevance, recall, and precision** of the sources cited. Benchmark datasets: BEIR (Benchmarking-IR), MS MARCO, and Natural Questions (NQ).
- **Hint:** The three properties are the three bullets in the "Evaluation Focus" box of the Level 3 diagram.

## Q9. NDCG@k and Recall@k can both be computed on the same top-k result set. What does NDCG@k respond to that Recall@k is completely blind to?
- Type: explain-why
- **Answer:** Ordering. NDCG@k measures ranking quality, rewarding highly relevant documents placed near the top, so it changes if you reorder the same k results. Recall@k only asks what percentage of all relevant documents appear anywhere in the top k, so a relevant document at rank 1 and the same document at rank 10 are identical to it. Precision@k is equally blind to order; MRR responds to order but only to the position of the *first* relevant result.
- **Hint:** Take a fixed set of five results, shuffle them, and ask which metrics move.

## Q10. A retriever returns the top 5 for a query, and the knowledge base holds 5 relevant documents in total. The results are `x R R x R` (R = relevant). Compute Recall@5, Precision@5, and MRR, then say which single metric a reranker could improve.
- Type: application
- **Answer:** Recall@5 = 3/5 = 0.60 (three of the five relevant documents found). Precision@5 = 3/5 = 0.60 (three of the five returned were relevant). MRR = 1/2 = 0.50 (first relevant result sits at rank 2). A reranker changes order but not membership, so it can improve MRR (and NDCG@5), but Recall@5 and Precision@5 cannot move, the same five documents are still the ones retrieved.
- **Hint:** Recall and Precision tie at 0.60 here only because k happens to equal the number of relevant documents. Don't read that as them measuring the same thing.

## Q11. What is the "core challenge" of Level 4, Grounded Generation, and name two metrics used to measure it.
- Type: recall
- **Answer:** Core challenge: preventing hallucination, verifying the output is a faithful synthesis of the provided context rather than the LLM "freelancing." Metrics (any two): Faithfulness, Answer Relevancy, Context Precision, Context Recall (or, on the generation-quality side specifically: Faithfulness, Groundedness, Hallucination Rate, Completeness).
- **Hint:** The module states this level's core question and core challenge as two separate, explicit lines.

## Q12. Split the Level 4 metrics into the "retrieval half" and the "generation half" of a RAG answer. Why does the module insist these two halves fail independently?
- Type: explain-why
- **Answer:** Retrieval half: Context Precision and Context Recall (do you even have the right material). Generation half: Faithfulness, Groundedness, Hallucination Rate, Completeness (given that material, did the model use it correctly and fully). They fail independently because you can have perfect retrieval with a model that ignores its context and hallucinates anyway, or flawless, faithful generation built on incomplete retrieved context. The practical upshot is a diagnostic order: read the retrieved context before judging the answer, or you'll tune prompts to fix what is actually a retrieval bug.
- **Hint:** Two of these metrics have the word "Context" in the name. That's not a coincidence.

## Q13. A RAG system retrieves chunks about entirely the wrong contract, and the answer faithfully and completely summarizes that wrong contract. Which metrics look good, which one catches the failure, and which half of the RAG engine is broken?
- Type: application
- **Answer:** Faithfulness, Groundedness and Completeness all look good, the answer genuinely does follow from the context it was given. The failure is caught on the retrieval side, by Context Recall (the material needed to answer was never retrieved), and Answer Relevancy would also flag that the answer doesn't address the user's actual query. The broken half is retrieval, not generation. This is the case that shows why a high Faithfulness score read in isolation can be actively misleading.
- **Hint:** Faithful to *what*? Ask what the answer is faithful to before treating a high score as good news.

## Q14. In Agentic RAG, a Router picks the wrong knowledge base. At which level does this failure originate, and why might the Level 4 metrics fail to reveal it?
- Type: application
- **Answer:** It originates at Level 3 (Retrieval), the wrong knowledge base means the wrong context. Level 4 metrics can miss it because the generator may be perfectly faithful and grounded with respect to the context it received, so Faithfulness stays high while the answer is useless. More generally, adding agency adds decision points, and each new decision point is a new place for a Level 3 or Level 4 failure to originate, which is why evaluation matters more, not less, once RAG becomes agentic.
- **Hint:** The routing decision happens before retrieval runs. Which pillar owns everything from that decision through to the context handed to the LLM?
