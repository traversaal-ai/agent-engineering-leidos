# Module 4: Exercises

Exercises 1-5 need no coding and no running app — they use the module's own diagrams, pain-point examples, and comparison tables. Exercises 6 and 7 run against [`axis/`](../axis/), the module's demo; setup is in the module [`README.md`](../README.md).

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

## Exercise 3: Diagnose the pillar

**Goal:** Practice placing a described failure on the Five Pillars of Evaluation, rather than just reciting the pyramid.

**Steps:**
1. For each of the following five failures, name the single level (1-5) it belongs to and the domain that level sits in: (a) the system answers correctly but each response costs three times the budget and takes eight seconds, (b) the correct passage exists in the knowledge base but never appears in the top 10 results, (c) the answer confidently states a figure that appears nowhere in the retrieved chunks, (d) given all the right facts in the prompt, the model still draws the wrong conclusion from them, (e) the agent had a working search tool available and simply never called it.
2. For (c) and (b) specifically, explain why fixing them requires changing two completely different parts of the system.
3. Take failure (e) and argue the case that it might *actually* be a Level 3 problem in disguise. What would you need to check to rule that out?

**Done when:** All five failures have a level and a domain, you have written the two-different-parts explanation for (b) vs. (c), and you have named the specific thing you'd inspect to test the claim in step 3.

## Exercise 4: Compute the retrieval metrics by hand

**Goal:** Feel why the four Level 3 metrics disagree, by scoring the same result set four ways. The worked example in `reference/rag-evaluation.md` covers the method; this uses different numbers.

**Steps:**
1. A knowledge base contains **4 relevant documents** for a query. The retriever returns the top 5, which land like this (`R` = relevant, `x` = not):

   ```
   rank:      1     2     3     4     5
   result:    x     R     x     x     R
   ```

   Compute **Recall@5**, **Precision@5**, and **MRR**. Show the fraction, not just the decimal.
2. Now suppose a reranker reorders these exact five results to `R R x x x`. Recompute all three. Exactly one of them changes, name which, and explain why the other two cannot move under any reordering.
3. Two of the four relevant documents never appeared in the top 5 at all. Explain in one or two sentences why no reranker can fix that, and name the parts of the pipeline where the fix would actually have to happen.
4. A colleague reports "our Precision@5 is 1.0, so retrieval is solved." Describe a result set where that is literally true and retrieval is still badly broken, and name the metric that would expose it.

**Done when:** You have three metrics computed before and after the rerank, an explanation of which moved and why, and a written answer to the "precision is great" claim in step 4.

## Exercise 5: Retrieval half or generation half?

**Goal:** Apply the diagnostic order from Concept 9, check the retrieved context before judging the answer, to four failing answers.

**Steps:**
1. For each of the following, decide whether the failure sits in the **retrieval half** or the **generation half**, and name the single metric that would catch it: (a) the retrieved chunks contain the full refund policy, but the answer cites a 60-day window that appears nowhere in them, (b) the question asked for both the price and the delivery timeline, the chunks contain both, and the answer covers only price, (c) the chunks retrieved are all about a different contract entirely, and the answer faithfully summarizes that wrong contract, (d) the chunks are correct but padded with fifteen paragraphs of unrelated boilerplate, and the answer wanders off-topic.
2. Case (c) is the interesting one: its **Faithfulness score would be high** while the answer is useless. Explain how that is possible, and what it tells you about reading generation metrics in isolation.
3. Pick whichever case you found hardest and write down what you would have inspected *first* to classify it, in one sentence.

**Done when:** All four cases have a half and a named metric, you have explained the high-Faithfulness-but-useless case in (c), and you have stated your first inspection step.

---

## Exercise 6: Find the question where orchestration is a waste of money

**Goal:** Break the intuition that the more sophisticated system is the better one. Requires a running Axis with the demo corpus loaded.

**Steps:**
1. Ask **"When is payment due on a correct invoice?"** under Naive RAG, then the identical question under Agentic RAG. Record, for each run: the answer, the number of LLM calls, the total cost, and the latency.
2. Write down what the agentic run spent the extra calls on. Name each stage from its trace, and say what decision that stage made.
3. Now ask **"What is the contractor entitled to if furnished equipment arrives more than thirty days late, and how is it granted?"** under both strategies. Record the same four things, and read the *retrieved context* for each run before you read either answer — the diagnostic order from Concept 9.
4. The second question's agentic run costs roughly what the first one's did. Explain, in two sentences, why the same spend is waste on question 1 and the whole point on question 2. Name the specific stage that makes the difference.
5. Open the router's `reason` on both agentic runs. It is model-authored, so it is a claim you can disagree with. Do you? Write one sentence saying whether the classification was right and how you can tell.

**Done when:** You have four measurements per run across four runs, a stage-by-stage account of what the extra money bought in each case, and a written answer to why identical spend is wasteful in one and necessary in the other.

## Exercise 7: Break the semantic cache, then explain why it broke

**Goal:** Feel the difference between matching words and matching meaning, and find the failure mode that a cache keyed on raw text will always have. Requires a running Axis.

**Steps:**
1. With the cache on, ask a question, then ask it again with different punctuation and capitalisation. Confirm the second one hits the cache, and note what it cost.
2. Now ask the *same question genuinely paraphrased* — every content word swapped, meaning identical. Record the similarity score and whether it hit. If you are running offline against the fake embedder, predict the result before you run it, then explain the result from what you know about how a bag-of-words embedding is computed.
3. Ask **"When did the master services agreement take effect?"**, then the follow-up **"How long is it?"**. Look at the trace and identify which stage ran *before* the cache was consulted, and why the ordering has to be that way. What would the cache have returned if it had been keyed on the four words as typed?
4. Design a question that *should* be refused by the cache even on an exact repeat. Say what property of the question makes a cached answer wrong, and name the mechanism that is supposed to catch it.
5. From steps 2 and 4, write down the two distinct ways a semantic cache can be wrong: one where it misses something it should have hit, and one where it hits something it should have missed. Which is more dangerous in a production system, and why?

**Done when:** You have a hit, a miss, a similarity score you can explain, an account of why the rewriter runs before the cache lookup on a follow-up, and a written comparison of the two failure directions.
