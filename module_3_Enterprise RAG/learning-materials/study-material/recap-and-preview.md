# Module 3: Recap & Preview (15-Minute Warm-Up)

## Recap from Module 02

Before this module starts, you should be comfortable with:

- The Claude Code environment: project configuration, permissions, and context management
- `CLAUDE.md` and Skills, for reusable instructions and repeatable development workflows
- MCP, for connecting external tools, APIs, data sources, and services
- Creating a structured PRD, and turning requirements into an implementation plan
- Building, testing, debugging, and iterating a working product with Claude Code

If any of those feel shaky, it's worth a quick pass back through Module 1 & 2's `study-material/lesson.md` and `reference/` folder before continuing, this module assumes you can use Claude Code comfortably and builds a new capability, retrieval, on top of that foundation.

## Where this fits in the course

```
WEEK 1              WEEK 2                  WEEK 3 (this module)     WEEK 4                    WEEK 5                 WEEK 6                    WEEK 7
Intro to AI          Skills, CLAUDE.md &     Enterprise RAG           Sub-Agents,               Voice Agents &          Guardrails,               Demo Day
Agents & Agent       Agent Operating         Systems                 Multi-Agent               Conversational          Evaluations &
Harness              System                                          Foundations &              Interfaces              Reliability
                                                                       Coordination
```

Week 3 sits between "you can build a working app with Claude Code" (Weeks 1-2) and "you can coordinate multiple agents" (Week 4). Retrieval is the specific capability this week adds: giving an agent access to knowledge it wasn't trained on, reliably and at enterprise scale.

## Coming up (Module 3: Enterprise RAG)

What you'll be able to do after this session:

- Explain why LLMs need RAG at all, the context window limit and the "LLMs don't know your data" problem
- Describe the three stages of any RAG pipeline: Ingestion, Retrieval, Generation
- Explain what an embedding and a vector database are, and how vector search differs from keyword search
- Name the five chunking strategies and pick the right one for a given source document
- List naive RAG's specific pain points: irrelevant retrieval, poor summarization, weak comparison, no multi-hop reasoning, no memory, no permissions
- Describe the Enterprise RAG architecture, and which stage fixes which naive-RAG pain point

**Watch for:** the line "LLMs don't know your data." Nearly everything in this module is solving one consequence or another of that single fact. If you lose the thread at any point, come back to it.

## If you only remember one thing walking into class

> RAG doesn't make an LLM smarter. It gives the LLM something to actually be grounded in, your own data, retrieved just in time, instead of guessed from what it memorized during training.

## Not covered this module

Agentic RAG (routing, one-shot query planning, tool use, conversation memory), multi-agent systems, and RAG evaluation are next class's material. This module stops at the Enterprise RAG architecture and its benefits, it deliberately does not go further into how an agent decides to use RAG as one tool among several, or how you'd measure a RAG system's quality once it's built. Hold onto the open question at the end of Concept 8: which naive-RAG pain point does routing-to-a-knowledge-base-once not fully solve? That's exactly where next class picks up.
