# Module 4: Recap & Preview (15-Minute Warm-Up)

## Recap from Module 03

Before this module starts, you should be comfortable with:

- Introduction to Naive RAG & Enterprise RAG
- What is Chunking & why do we need it?
- Different Chunking Strategies in RAG
- Naive RAG & its Pain Points

If any of that feels shaky, it's worth a quick pass back through Module 3's `study-material/lesson.md` and `reference/` folder before continuing, this module builds a new capability, agency, on top of that retrieval foundation, and introduces a second, separate topic, voice AI architectures.

## Where this fits in the course

```
WEEK 1              WEEK 2                  WEEK 3                  WEEK 4 (this module)     WEEK 5                  WEEK 6                    WEEK 7
Intro to AI          Skills, CLAUDE.md &     Enterprise RAG          Sub-Agents,               Voice Agents &          Guardrails,               Demo Day
Agents & Agent       Agent Operating         Systems                 Multi-Agent               Conversational          Evaluations &
Harness              System                                          Foundations &              Interfaces              Reliability
                                                                       Coordination
```

Week 4 sits between "you can build a working Enterprise RAG pipeline" (Week 3) and "you can coordinate multiple agents" and "you can build voice agents" (Weeks 4-5 together). This week specifically adds: build retrieval, reranking, rewriting, and grounding; add chunking for better retrieval; use sub-agents for specialized tasks; coordinate agents with shared state and tools; design patterns for multi-agent collaboration.

## Coming up (Module 4: Agentic RAG & Voice AI)

What you'll be able to do after this session:

- Explain Naive RAG and its pain points (recap)
- Describe what Agentic RAG is
- Explain routing, decomposition, and semantic caching
- Compare Naive RAG vs. Agentic RAG
- Understand Voice AI Architectures: Speech-to-Speech (S2S) and Cascaded (STT → LLM → TTS)

**Watch for:** the line "RAG is just one Tool." Nearly everything in the Agentic RAG half of this module is about what changes once RAG stops being the only thing a query can do and becomes one option an agent chooses among.

## If you only remember one thing walking into class

> Four small ingredients, Routing, One-Shot Query Planning, Tool Use, Conversation Memory, are what turn a fixed RAG pipeline into something that can decide what to do next. Voice AI has the same kind of choice built into it: one model doing everything at once (Speech-to-Speech), or three swappable stages chained together (Cascaded), and neither one wins on every dimension.

## Not covered this module

Full Agents (ReAct, Dynamic Planning + Execution) are named on the agent-ingredients spectrum but not built out in depth here, that, along with sub-agent coordination and multi-agent design patterns, is Week 4's broader course-level material and Week 5's continued focus on Voice Agents & Conversational Interfaces. This module also does not build a production voice agent end to end, it covers the two architectures (S2S, Cascaded), the framework landscape, and a live demo (Iris), not a hands-on build.
