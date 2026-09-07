"""The `Retriever` interface — what the pipelines and the agent loop are typed against.

One implementation ships: `VectorRetriever` (Chroma). **The protocol is not here to make
a second one cheap** — graph retrieval is a stated non-goal (PRD Section 3) and this is
not a placeholder for it. It earns its place on two narrower grounds:

- **It is the boundary that keeps retrieval out of the orchestration.** The Router,
  decomposer and ReAct loop hold a `Retriever`, so none of them can reach into Chroma,
  read a collection name, or depend on how similarity is scored. That is what makes them
  unit-testable with a twenty-line double, which two test modules already do.
- **It is a written contract, enforced.** `tests/contract/test_retriever_conformance.py`
  is the definition of what a retriever owes its caller — every rule in the two
  docstrings below is a test there, not a comment. Any future implementation inherits
  that suite.

A protocol with one implementation is a real cost, and stating the justification at its
actual strength is deliberate: see System Design Section 9, which records what this used
to be defended by and why that argument no longer applies.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ai_backend.contracts.models import RetrievedContext


@runtime_checkable
class Retriever(Protocol):
    name: str

    async def retrieve(
        self,
        query: str,
        *,
        session_id: str,
        top_k: int = 5,
    ) -> RetrievedContext:
        """Fetch context for a query.

        Returning an empty `RetrievedContext` is a legitimate, expected outcome,
        not an error: System Design Section 11 requires "no sufficiently relevant
        content found" be surfaced as a visible trace step. Implementations must
        not raise merely because nothing cleared the relevance threshold.
        """
        ...

    async def is_ready(self, session_id: str) -> bool:
        """Whether this retriever has an index for the session at all.

        **Distinct from `retrieve` returning nothing**, and that distinction is the
        point: "you have not indexed anything yet" and "your documents do not answer
        that" are different facts about a session, with different remedies, and a caller
        that conflated them would tell a student their documents lack an answer they
        never uploaded. Pinned by
        `test_is_ready_distinguishes_no_index_from_no_match`.
        """
        ...
