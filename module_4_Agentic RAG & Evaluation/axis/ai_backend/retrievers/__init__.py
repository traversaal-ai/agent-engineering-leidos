"""Retriever implementations. One, and one is the design.

- `VectorRetriever` — Chroma, dense with optional BM25 + RRF hybrid. **Both strategies
  hold the same instance**, wired once in `runtime.py`.

Sharing it is not an optimisation, it is the experiment's control: if Naive RAG and
Agentic RAG retrieved differently, no difference between their answers could be
attributed to the orchestration, and the one comparison Axis exists to make would be
measuring two variables at once.

**A second retriever is a non-goal** (PRD Section 3), so if one appears here, the
comparison model in System Design Section 9 needs rewriting first — not after. What
`hybrid` demonstrates is that *retrieval quality* is tunable within one retriever, which
is the honest version of the lesson a second implementation was going to teach.
"""
