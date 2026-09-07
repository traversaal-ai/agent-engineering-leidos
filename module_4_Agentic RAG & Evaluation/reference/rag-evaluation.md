# Reference: Evaluating RAG

Deep dive behind the module's Concepts 7-9, "Evaluating RAG." This lays out the Five Pillars of Evaluation and then goes one level deeper into the two the module focuses on: Retrieval Evals and Generation Evals.

## A hierarchy of capability, the Five Pillars of Evaluation

```
                    Level 5: Agent Evals              -> Domain 3: The Agent Interface
        Level 4: Generation Evals
    Level 3: Retrieval Evals                          -> Domain 2: The RAG Engine  (this module's focus)
Level 2: Reasoning Evals
Level 1: LLM Quality + Efficiency Evals                -> Domain 1: The LLM Core
```

The five levels build on each other like a pyramid, grouped into three domains: **Domain 1, The LLM Core** (Level 1 LLM Quality + Efficiency, Level 2 Reasoning), **Domain 2, The RAG Engine** (Level 3 Retrieval, Level 4 Generation), and **Domain 3, The Agent Interface** (Level 5 Agent Evals). This module zooms into Domain 2, Levels 3 and 4, the RAG Engine specifically.

## The five pillars, one core question each

Each level has a single question it exists to answer. Reading them bottom-up shows why the pyramid is a pyramid, every level assumes the one beneath it already works:

- **Level 1, LLM Quality + Efficiency.** *Core question:* is the underlying model good enough, and cheap and fast enough, to build on at all?
- **Level 2, Reasoning.** *Core question:* can the model actually reason over what it is given?
- **Level 3, Retrieval.** *Core question:* can the system find the right information efficiently?
- **Level 4, Generation.** *Core question:* is the final answer grounded in the retrieved documents?
- **Level 5, Agent.** *Core question:* does the agent, using the whole stack as tools, accomplish the task it was given?

The ordering is the useful part. A Level 4 failure is only meaningful once Level 3 passes, there is no point asking "did the model use its context faithfully?" when the retriever handed it the wrong context in the first place. Equally, a Level 5 agent failure is often just a Level 3 failure wearing a costume.

**Levels 1, 2 and 5 are named here for orientation only.** This module does not go into them, it covers Domain 2, Levels 3 and 4, in depth.

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

### Worked example: one result set, four different scores

The point above is easy to nod along to and hard to feel until you score the same result set four ways. Take one query against a knowledge base that contains **5 relevant documents in total**. The retriever returns the top 5, and they land like this (`R` = relevant, `x` = not relevant):

```
rank:      1     2     3     4     5
result:    x     R     R     x     R
```

So: 3 of the 5 retrieved documents are relevant, the first relevant one sits at rank 2, and 5 relevant documents exist in the corpus overall.

- **Recall@5** = relevant found / relevant that exist = 3 / 5 = **0.60**. Two relevant documents never surfaced at all. This is the *completeness* view, and it is the only one of the four that knows the two missing documents exist.
- **Precision@5** = relevant found / results returned = 3 / 5 = **0.60**. Two of the five slots were wasted on noise. This is the *cleanliness* view, and it would not change at all if the corpus held 50 more relevant documents.
- **MRR** = 1 / rank of first relevant result = 1 / 2 = **0.50**. This is the *how fast* view. It looks only at rank 2 and is completely blind to the two other relevant documents further down.
- **NDCG@5** is the *order* view. It is the only metric of the four that would move if you did nothing but reorder these same five results. Promote the rank-5 relevant document to rank 1 and Recall@5, Precision@5 all stay exactly where they are, MRR improves to 1.0, and NDCG@5 improves because relevance moved toward the top.

Two lessons worth carrying out of this. First, **Recall@5 and Precision@5 coincidentally match here at 0.60** purely because k happens to equal the number of relevant documents, they are answering completely different questions and will diverge the moment that stops being true. Second, a reranker, which changes ordering but not membership, can only move NDCG@k and MRR. If your problem is that two relevant documents never made the top 5 at all, no amount of reranking will fix it, that is a recall problem, and it lives further upstream in chunking, embedding, or how many results you retrieve.

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

### Diagnosing which half failed

Because the two halves fail independently, the useful diagnostic habit is to fix the half before asking about the half after. Given a bad answer, work in this order:

1. **Look at the retrieved context first, before the answer.** If the material needed to answer the question isn't in it, you have a Context Recall problem and the generation metrics will be misleading, the model was never given a chance.
2. **If the context is full of unrelated material**, that's Context Precision, and it degrades generation indirectly by burying the signal.
3. **Only if the context is right** does a wrong answer become a genuine generation failure: a claim that appears nowhere in the context is caught by Faithfulness and Groundedness and counted by Hallucination Rate; an answer that's true and grounded but only addresses part of what was asked is caught by Completeness; an answer that's grounded and complete but about the wrong thing entirely is caught by Answer Relevancy.

The trap this avoids is tuning prompts to fix what is actually a retrieval bug, the most common wasted week in RAG work.

## Where evaluation meets Agentic RAG

The Agentic RAG ingredients from Concept 6 are not exempt from this pyramid, they just change *where* a failure shows up:

- **Routing** picking the wrong knowledge base is a **Level 3** failure. The generator may then be perfectly faithful to context that came from the wrong place, so Faithfulness stays high while the answer is useless. This is exactly the case where a good Level 4 score hides a Level 3 bug.
- **One-Shot Query Planning** gives you a recall lever, decomposing a comparison query into sub-queries retrieves for each half separately, which is often what raises Context Recall on the multi-hop and comparison pain points from Module 3. But each sub-response still has to be synthesized, and synthesis is where a final answer can drift from what any individual sub-query actually retrieved, a **Level 4** faithfulness risk that naive RAG doesn't have.
- **Tool Use** moves part of the answer outside the retrieval corpus entirely (an API, a SQL database). Grounding then has to be judged against the tool's output, not just the vector store.
- **Conversation Memory** means the context feeding generation is no longer only retrieved documents. An answer can be faithful to conversation history while unfaithful to the retrieved documents, and vice versa.

The through-line: adding agency adds decision points, and every new decision point is a new place for a Level 3 or Level 4 failure to originate. Evaluation is what tells you which one you actually have.

**Check:** A RAG system retrieves three highly relevant, complete chunks (high Context Precision and Context Recall), but the generated answer states a fact that appears nowhere in those three chunks. Which specific Level 4 metric would catch this, and does the problem here sit in the RAG Engine's retrieval half or its generation half?
