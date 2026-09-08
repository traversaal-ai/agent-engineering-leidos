"""The agent components: everything Agentic RAG has and Naive RAG does not.

They live here rather than inside `pipelines/agentic_rag.py` because each one is a
**separately testable decision**, and folding five of them into one pipeline method
makes five things that can be asserted about into one that cannot. The router's
classification, the decomposer's split, the rewriter's resolution, the cache's
hit/miss threshold and the loop's escalation each have their own acceptance criteria in
PRD Section 6 and their own unit tests.

That is the whole justification, and it is narrower than the one it replaces. This
package used to be defended as the shared half of two agentic strategies — Agentic RAG
and a graph twin, differing only in the injected `Retriever`. That twin is a non-goal
now (PRD Section 3), so the reuse argument is gone and the testability one has to carry
it alone. See System Design Section 9.

Nothing in this package names a concrete retriever, provider, or store — only the
contracts. That still matters: it is what lets every component above be tested against
a twenty-line double instead of a live Chroma.
"""

from ai_backend.agents.decomposer import Decomposer
from ai_backend.agents.react import ReActLoop
from ai_backend.agents.router import RouteDecision, Router
from ai_backend.agents.spend import QuerySpend
from ai_backend.agents.tools import DocumentSearchTool

__all__ = [
    "Decomposer",
    "DocumentSearchTool",
    "QuerySpend",
    "ReActLoop",
    "RouteDecision",
    "Router",
]
