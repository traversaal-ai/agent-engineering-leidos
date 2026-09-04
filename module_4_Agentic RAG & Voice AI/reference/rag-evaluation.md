# Reference: Evaluating RAG (Appendix)

Deep dive on the module's Appendix section, "Evaluating RAG." This picks the thread back up on the Five Pillars of Evaluation and goes one level deeper into two of them: Retrieval Evals and Generation Evals.

## Recap: A hierarchy of capability, the Five Pillars of Evaluation

```
                    Level 5: Agent Evals              -> Domain 3: The Agent Interface
        Level 4: Generation Evals
    Level 3: Retrieval Evals                          -> Domain 2: The RAG Engine  (this module's focus)
Level 2: Reasoning Evals
Level 1: LLM Quality + Efficiency Evals                -> Domain 1: The LLM Core
```

The five levels build on each other like a pyramid, grouped into three domains: **Domain 1, The LLM Core** (Level 1 LLM Quality + Efficiency, Level 2 Reasoning), **Domain 2, The RAG Engine** (Level 3 Retrieval, Level 4 Generation), and **Domain 3, The Agent Interface** (Level 5 Agent Evals). This module's Appendix zooms into Domain 2, Levels 3 and 4, the RAG Engine specifically.

## Level 3: Knowledge Access (Retrieval Evals)

**Core question:** Can the system find the right information efficiently?

A powerful reasoning engine is useless if it operates on flawed or incomplete information. This evaluation pillar measures the performance of the retrieval system that feeds context to the LLM. What's being measured here is the **relevance, recall, and precision** of the sources it cites.

**Evaluation focus, visualized:**

```
[Vector DB + retrieval pipeline] -> [Context Filter] -> Evaluation Focus:
                                                          - Relevance: Does the retrieved context
                                                            directly answer the query?
                                                          - Recall: Did the system pull all
                                                            necessary documents?
                                                          - Precision: Is the retrieved data
                                                            free of distracting, irrelevant noise?
```

### Common benchmark datasets

- **BEIR (Benchmarking-IR)**: A diverse collection of information retrieval tasks.
- **MS MARCO**: A large-scale dataset for passage ranking and reading comprehension.
- **Natural Questions (NQ)**: Queries from real Google search users, requiring systems to find answers in Wikipedia articles.

### Key performance metrics

- **NDCG@k (Normalized Discounted Cumulative Gain)**: Measures ranking quality, rewarding highly relevant documents placed at the top.
- **Recall@k**: What percentage of all relevant documents were found in the top "k" results?
- **Precision@k**: Of the top "k" documents retrieved, what percentage were relevant?
- **Mean Reciprocal Rank (MRR)**: Measures the rank of the first correct answer.

Note what these four metrics are each sensitive to: NDCG@k cares about *order* (a relevant document buried at position 10 scores worse than the same document at position 1); Recall@k cares about *completeness* (did you miss anything relevant, anywhere in the top k); Precision@k cares about *cleanliness* (how much of what you retrieved was actually useful); MRR cares about *how fast* the first right answer shows up.

## Level 4: Grounded Generation (Generation Evals)

**Core question:** Is the final answer grounded in the retrieved documents?

This is the critical test to ensure the LLM isn't hallucinating or "freelancing" with its creativity. We must verify the output is a faithful synthesis of the provided context. **Core challenge:** preventing hallucination.

Evaluating RAG systems focuses less on standard benchmarks (the kind used for Level 3) and more on a suite of metrics that measure the quality of the generation process *relative to the retrieved context*:

- **Faithfulness**: Does the generated answer directly follow from the provided context? This is a direct measure against hallucination.
- **Answer Relevancy**: Is the answer relevant to the user's original query?
- **Context Precision**: Is the retrieved context necessary and concise for answering the query? (Signal-to-noise ratio.)
- **Context Recall**: Did the retriever find all the necessary information from the knowledge base to answer the query completely?

**Generation quality, visualized as a pipeline:**

```
Retrieved Facts  ->  Synthesis Filter  ->  Faithful Output
[Evaluate: Retrieval Quality]         [Evaluate: Generation Quality]
```

**Generation quality metrics:**

- **Faithfulness**: Response stays within retrieved context.
- **Groundedness**: Claims are supported by source data.
- **Hallucination Rate**: Frequency of unsupported outputs.
- **Completeness**: Covers all aspects of the query.

Note the overlap and the distinction between Context Precision/Context Recall (which are about the *retrieval* half of a RAG answer, do you even have the right material) and Faithfulness/Groundedness/Hallucination Rate/Completeness (which are about the *generation* half, given that material, did the model actually use it correctly and fully). A RAG system can fail at either half independently: perfect retrieval with a model that ignores its context and hallucinates anyway, or flawless, faithful generation built on incomplete retrieved context.

**Check:** A RAG system retrieves three highly relevant, complete chunks (high Context Precision and Context Recall), but the generated answer states a fact that appears nowhere in those three chunks. Which specific Level 4 metric would catch this, and does the problem here sit in the RAG Engine's retrieval half or its generation half?
