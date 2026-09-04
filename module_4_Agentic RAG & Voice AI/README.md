# Module 4: Agentic RAG & Voice AI

Study material for Week 4, built strictly from the module's own slide deck (`Module-4-Agentic-RAG-&-Voice-AI-Leidos-x-UBLA-x-Traversaal.pptx.pdf`). This folder does not contain a finished app, it contains the reference and study material for the concepts taught in class.

## Learning objectives

By the end of this module you can:

- Explain Naive RAG and its pain points (recap from Module 3)
- Describe what Agentic RAG is
- Explain routing, decomposition (one-shot query planning), and semantic caching
- Compare Naive RAG vs. Agentic RAG
- Understand Voice AI architectures: Speech-to-Speech (S2S) and Cascaded (STT → LLM → TTS)
- Name the voice AI frameworks landscape (Model-Agnostic Orchestrators vs. Full-Stack Managed Platforms)
- Describe the Retrieval and Generation levels of RAG evaluation (from the module's Appendix)

## Prerequisites

You've completed Module 3 (Enterprise RAG) and are comfortable with the three-stage RAG pipeline (Ingestion, Retrieval, Generation), the five chunking strategies, naive RAG's four pain points, and the Enterprise RAG architecture that addresses them. This module builds directly on that foundation, first by making RAG agentic, then by introducing a new, separate capability: voice.

## Folder map

```
study-material/           the lesson content, organized the way the module was taught
  lesson.md                 full teaching content: RAG recap, Agentic RAG, Voice AI architectures, frameworks, key takeaways, appendix
  key-concepts.md           quick glossary for this module
  exercises.md              hands-on exercises, no coding, applied to the module's own scenarios and tables
  quiz.md                   14 questions with answers and hints
  recap-and-preview.md      a 15-minute pre-class warm-up
reference/                deep dives the study material points to
  agentic-rag.md             routing, one-shot query planning, tool use, conversation memory
  voice-ai-architectures.md  Speech-to-Speech vs. Cascaded, pros/cons, cost & latency comparisons
  voice-ai-frameworks.md     the voice stack's four layers, orchestrators vs. managed platforms
  rag-evaluation.md          Level 3 Retrieval Evals and Level 4 Generation Evals (from the Appendix)
  glossary.md                the fuller source-of-truth term list
```

## How to use this folder

| Step | File | What happens |
|------|------|---------------|
| 0. Warm up | [`study-material/recap-and-preview.md`](study-material/recap-and-preview.md) | 15-minute refresher on Module 3 and where this module fits in the course |
| 1. Learn the concepts | [`study-material/lesson.md`](study-material/lesson.md) | The full lesson, in the same order as the class |
| 2. Go deeper | [`reference/`](reference/) | Deep dives on Agentic RAG, Voice AI architectures, Voice AI frameworks, and RAG evaluation |
| 3. Practice | [`study-material/exercises.md`](study-material/exercises.md) | No-coding exercises applied to the module's own scenarios |
| 4. Self-check | [`study-material/quiz.md`](study-material/quiz.md) | 14 questions with answers and hints |
| 5. Quick review | [`study-material/key-concepts.md`](study-material/key-concepts.md) and [`reference/glossary.md`](reference/glossary.md) | Fast glossary lookups |

There are no coding examples or notebooks in this module by design, matching how the class itself was taught: conceptual content on Agentic RAG and Voice AI architectures, plus two live demos (Naive RAG vs. Agentic RAG, and Iris, Traversaal.ai's voice customer support agent) that are referenced but not rebuilt here.
