"""The evaluation harness. Grows one slice per milestone.

System Design Section 12 is explicit that this is built incrementally alongside
each strategy rather than in one pass at the end, and CLAUDE.md forbids starting
a milestone before the previous one's evaluation slice passes. So this package is
not a reporting afterthought — it is the gate between milestones.

Planned shape:

- `golden.py`   — the Q&A set, loaded from `evaluation/golden/*.yaml`. Per document
                  type (text, table, image), plus the compound, multi-hop and
                  conversational questions whose whole purpose is to fail on a single
                  retrieval pass so that the agentic win is measured rather than
                  assumed.
- `retrieval.py` — precision@k, document recall and per-question fact recall.
- `answers.py`  — groundedness and citation accuracy, applied *identically* to both
                  strategies. PRD Section 7 flags LLM-as-judge bias toward
                  verbose answers as a live risk, so the rubric is worth pinning
                  down before it is used to declare a winner.
- `report.py`   — the cross-strategy comparison behind Milestone 4.

It reads traces from the `AgentStep` store rather than instrumenting pipelines
separately. That is what keeps a scored run and the trace a student is looking at
the same run.
"""
