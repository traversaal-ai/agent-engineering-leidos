# Module 4: Agentic RAG & Evaluation

## Learning objectives

By the end of this module you can:

- Explain Naive RAG and its pain points (recap from Module 3)
- Describe what Agentic RAG is
- Explain routing, decomposition (one-shot query planning), and semantic caching
- Compare Naive RAG vs. Agentic RAG
- Place a RAG failure on the Five Pillars of Evaluation and name the domain it belongs to
- Describe Level 3 Retrieval Evals: relevance, recall, and precision, and what each key metric is sensitive to
- Describe Level 4 Generation Evals, and tell a retrieval-half failure apart from a generation-half one

## Prerequisites

You've completed Module 3 (Enterprise RAG) and are comfortable with the three-stage RAG pipeline (Ingestion, Retrieval, Generation), the five chunking strategies, naive RAG's four pain points, and the Enterprise RAG architecture that addresses them. This module builds directly on that foundation, first by making RAG agentic, then by adding the discipline that tells you whether any of it works: evaluation.

## Folder map

```
study-material/           the lesson content, organized the way the module was taught
  lesson.md                 full teaching content: RAG recap, Agentic RAG, the Five Pillars, Levels 3 and 4, key takeaways
  key-concepts.md           quick glossary for this module
  exercises.md              hands-on exercises, no coding, applied to the module's own scenarios and metrics
  quiz.md                   14 questions with answers and hints
  recap-and-preview.md      a 15-minute pre-class warm-up
reference/                deep dives the study material points to
  agentic-rag.md             routing, one-shot query planning, tool use, conversation memory
  rag-evaluation.md          the Five Pillars, Level 3 Retrieval Evals and Level 4 Generation Evals, with a worked metric example
  glossary.md                the fuller source-of-truth term list
axis/                     a standalone application project kept alongside the module; not part of the
                          lesson material above and not referenced by it
```

## How to use this folder

| Step | File | What happens |
|------|------|---------------|
| 0. Warm up | [`study-material/recap-and-preview.md`](study-material/recap-and-preview.md) | 15-minute refresher on Module 3 and where this module fits in the course |
| 1. Learn the concepts | [`study-material/lesson.md`](study-material/lesson.md) | The full lesson, in the same order as the class |
| 2. Go deeper | [`reference/`](reference/) | Deep dives on Agentic RAG and RAG evaluation |
| 3. Practice | [`study-material/exercises.md`](study-material/exercises.md) | No-coding exercises applied to the module's own scenarios |
| 4. Self-check | [`study-material/quiz.md`](study-material/quiz.md) | 14 questions with answers and hints |
| 5. Quick review | [`study-material/key-concepts.md`](study-material/key-concepts.md) and [`reference/glossary.md`](reference/glossary.md) | Fast glossary lookups |

The lesson material contains no coding examples or notebooks by design, matching how the class itself was taught: conceptual content on Agentic RAG and on evaluating a RAG system, plus a live demo (Naive RAG vs. Agentic RAG) that is referenced but not rebuilt here.
