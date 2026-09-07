"""The `Pipeline` interface — one per strategy, four in total.

The Backend dispatches to a pipeline without knowing how an answer is produced;
that ignorance is the layer boundary from System Design Section 6.1, expressed as
a type.

`QueryContext` is what the Backend hands down: identity, budget, and the
strategy asked for. Note what is *not* in it — no API keys, no provider objects,
no store handles. Those are resolved inside the AI Backend from server-side
config, so a secret has no path to the Frontend even by accident.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from ai_backend.contracts.models import Answer, Strategy, new_id


class QueryBudget(BaseModel):
    """The remaining allowance for one query, computed by the Backend.

    The AI Backend treats these as hard limits and checks them before each
    external call. Passing the budget down rather than letting the AI Backend
    read caps from config keeps enforcement testable in isolation and keeps the
    Backend the single owner of what a session has already spent.
    """

    max_cost_usd: float
    max_llm_calls: int
    max_agent_iterations: int
    max_tool_calls: int
    # Web searches, bounded separately from tool calls: search is billed per request
    # rather than per token, so the token estimate that guards LLM calls cannot bound
    # it, and it is the only spend that leaves the machine for a third party.
    #
    # Defaulted so every existing construction of a budget — the evaluation harness,
    # a few dozen tests — keeps working without being rewritten to name a bound they
    # do not exercise. The Backend always passes it explicitly from settings.
    max_search_calls: int = 3


class Turn(BaseModel):
    """One exchange already had in this session.

    Persisted by the Backend and handed down here, because Section 6.1 puts
    persistence in the Backend and consumption in the AI Backend. The obvious
    alternative — the browser holding the transcript and posting it, which is what
    `reference/module_3_Enterprise RAG/` does — is not available: the ask form has
    to work with JavaScript disabled, and a client-supplied history would be a way
    to put arbitrary text into a prompt.
    """

    question: str
    answer: str


DEMO_CORPUS = "demo"
DEFAULT_CORPUS = "mine"

# The two corpora a session can hold. `demo` is the fixture set the labelled questions
# and the pain-point demonstrations were measured against; `mine` is whatever the
# student uploaded.
#
# A closed set on purpose. The corpus reaches here from a browser cookie, and it names
# an index scope — an open set would let a forged value address an arbitrary one. That
# scope would be empty, so the harm is nil, but "nothing can name a scope we did not
# define" is cheaper to hold than to reason about later.
CORPORA: tuple[str, ...] = (DEMO_CORPUS, DEFAULT_CORPUS)


def index_scope(session_id: str, corpus: str) -> str:
    """The key a session's chunks are stored and searched under.

    **This is the whole of the two-corpus implementation**, which is why it is four
    lines rather than a subsystem. `Retriever.retrieve` and every `VectorStore` method
    take `session_id` as an *opaque scope string*: Chroma writes it as chunk metadata
    and filters on equality, and `InMemoryVectorStore` uses it as a dict key. Neither
    interprets it. So two corpora need no change to the storage protocol, to either of
    its implementations, or to the `Retriever` contract — only a different string from
    the callers.

    The alternative was post-filtering retrieved chunks by `document_id`, which
    `summarize_session` already does for its document picker and which would have
    worked. It was rejected because the filter has to run *after* `top_k`: retrieval
    would have to over-fetch, and the effective `k` would depend on how the corpora
    happened to be split. Here `top_k` keeps meaning exactly what it means today, and
    BM25's `all_chunks(scope)` is corpus-scoped for free rather than needing a filter
    of its own.

    An unknown corpus falls back rather than raising, and to `mine` rather than `demo`:
    the fallback should land on the corpus that is empty until a student fills it, not
    on one holding documents they did not choose.
    """
    known = corpus if corpus in CORPORA else DEFAULT_CORPUS
    return f"{session_id}::{known}"


class QueryContext(BaseModel):
    session_id: str
    # Generated per query, and **passable** so a caller that does paid work *before* the
    # question exists can join it to the run it produced. Nothing does today; the field
    # stays settable because the alternative is a second trace holding half of one
    # turn's cost, on the page built to show what a turn costs.
    trace_id: str = Field(default_factory=new_id)
    strategy: Strategy
    question: str
    budget: QueryBudget
    # Which of the session's corpora this query searches.
    #
    # Not the same thing as `session_id`, and the split is the point: spend, the trace,
    # the conversation and the answer cache are all facts about the *session* and stay
    # keyed on it, while the index is keyed on the session **and** the corpus. A
    # student holds the demo set and their own documents at once and switches between
    # them; only retrieval changes.
    corpus: str = DEFAULT_CORPUS
    # What this session has already asked and been told, oldest first.
    #
    # **Read by the Rewriter and by nothing else.** Not the synthesis prompt: a fact
    # recalled from a conversation has no passage to cite, so using history as
    # evidence would produce exactly the uncited answer `pipelines/grounding.py`
    # withholds. Axis's memory resolves *references*; it does not carry *facts*.
    # `docs/Axis_Notebook_Alignment.md` §9 records this at length, because the
    # course material's own memory example is the fact-carrying kind and a student
    # will ask why Axis declines it.
    #
    # Naive RAG receives this and ignores it. It is the baseline, and a baseline
    # with a capability the thing measured against it has is not a baseline —
    # asserted by `test_the_baseline_never_remembers`.
    history: tuple[Turn, ...] = ()
    # Whether this query may be answered from the semantic cache.
    #
    # Capability-and-permission again, the same shape as `web_enabled`:
    # `AXIS_CACHE__ENABLED` decides whether a cache exists at all, this is the
    # student's switch on top of it, and the two are combined with `and`. Unlike the
    # web toggle it defaults to **on**, because the directions of harm are opposite
    # — a web call reaches a paid third party and drags a prompt-injection surface
    # in with it, where a cache hit only ever avoids spending. An instructor turns
    # it off to charge full price for a question the class has already asked.
    cache_enabled: bool = True

    @property
    def index_scope(self) -> str:
        """What retrieval is scoped to. See `index_scope` above.

        Every call that reaches a `Retriever` or a `VectorStore` passes this rather
        than `session_id` — and the two must not be confused, because passing the
        session id would search both corpora at once and quietly make every
        measurement on the Why-agentic page a measurement of the wrong thing.
        """
        return index_scope(self.session_id, self.corpus)
    # Whether this query may leave the uploaded documents.
    #
    # **Permission, not capability.** Whether a search provider exists at all is a
    # server-side configuration decision (`AXIS_SEARCH__PROVIDER`, read at startup);
    # this is the student's switch on top of it, and the two are combined with `and` in
    # `AgenticRagPipeline.run`. So it can only ever *narrow* what is reachable — no
    # value here can conjure a provider that was never configured, which is what keeps
    # a browser-supplied flag from being a way to reach the internet.
    #
    # Defaults to False: a web call is paid, goes to a third party, and carries the
    # prompt-injection exposure of System Design Section 6.5. Configuring a provider
    # makes the route *available*; asking for it is a separate act.
    web_enabled: bool = False


@runtime_checkable
class Pipeline(Protocol):
    strategy: Strategy

    async def run(self, ctx: QueryContext) -> Answer: ...
