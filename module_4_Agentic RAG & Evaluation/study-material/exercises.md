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
