# Module 4: Recap & Preview (15-Minute Warm-Up)

## Recap from Module 03

Before this module starts, you should be comfortable with:

- Introduction to Naive RAG & Enterprise RAG
- What is Chunking & why do we need it?
- Different Chunking Strategies in RAG
- Naive RAG & its Pain Points

If any of that feels shaky, it's worth a quick pass back through Module 3's `study-material/lesson.md` and `reference/` folder before continuing, this module builds a new capability, agency, on top of that retrieval foundation, and then adds the discipline that tells you whether any of it actually works: evaluation.

## Where this fits in the course

```
WEEK 1              WEEK 2                  WEEK 3                  WEEK 4 (this module)     WEEK 5                  WEEK 6                    WEEK 7
Intro to AI          Skills, CLAUDE.md &     Enterprise RAG          Sub-Agents,               Voice Agents &          Guardrails,               Demo Day
Agents & Agent       Agent Operating         Systems                 Multi-Agent               Conversational          Evaluations &
Harness              System                                          Foundations &              Interfaces              Reliability
                                                                       Coordination
```

Week 4 sits between "you can build a working Enterprise RAG pipeline" (Week 3) and "you can coordinate multiple agents" (Week 4's broader course-level material). This week specifically adds: build retrieval, reranking, rewriting, and grounding; add chunking for better retrieval; use sub-agents for specialized tasks; coordinate agents with shared state and tools; design patterns for multi-agent collaboration.

## Coming up (Module 4: Agentic RAG & Evaluation)

What you'll be able to do after this session:

- Explain Naive RAG and its pain points (recap)
- Describe what Agentic RAG is
- Explain routing, decomposition, and semantic caching
- Compare Naive RAG vs. Agentic RAG
- Place a RAG failure on the Five Pillars of Evaluation
- Describe Level 3 Retrieval Evals and Level 4 Generation Evals, and tell the two apart in practice

**Watch for:** the line "RAG is just one Tool." Nearly everything in the Agentic RAG half of this module is about what changes once RAG stops being the only thing a query can do and becomes one option an agent chooses among.

## If you only remember one thing walking into class

> Four small ingredients, Routing, One-Shot Query Planning, Tool Use, Conversation Memory, are what turn a fixed RAG pipeline into something that can decide what to do next. And every decision point you add is a new place for a failure to originate, which is why the second half of this module is evaluation: a pyramid where each level assumes the one beneath it works, and where a RAG answer can fail at its retrieval half or its generation half completely independently.

## Not covered this module

Full Agents (ReAct, Dynamic Planning + Execution) are named on the agent-ingredients spectrum but not built out in depth here, that, along with sub-agent coordination and multi-agent design patterns, is Week 4's broader course-level material. On the evaluation side, this module covers Domain 2 of the Five Pillars only, Level 3 (Retrieval) and Level 4 (Generation). Levels 1 and 2 (The LLM Core) and Level 5 (Agent Evals) are named for orientation but not taught here. The lesson itself teaches the metrics and the diagnostic reasoning rather than a build, but the module does ship a running evaluation harness: Axis computes Level 3 retrieval scores over a golden set and gates four measured ceilings, and `README.md` shows the two commands that produce them.
