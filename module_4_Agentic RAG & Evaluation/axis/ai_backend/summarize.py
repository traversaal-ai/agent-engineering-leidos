"""Summarizer mode — a structured overview of the indexed documents.

PRD Section 5: *"a structured overview of my documents without having to ask a
specific question first."*

**Not a strategy, deliberately.** It does not retrieve at all, so there is no
orchestration distinction to draw about it — it is not a `Strategy` member and never
appears in Compare mode. Adding it to that enum would make Compare's one variable stop
meaning orchestration, and `AgentStep.strategy` is persisted, so the vocabulary is not
cheap to change later.

**Its teaching job is a contrast rather than a comparison.** Summarization reads
*everything* and its cost scales with the size of the corpus; retrieval reads the
*relevant part* and its cost scales with the question. Put next to a query trace, that
is the clearest available illustration of why RAG exists at all — the alternative to
retrieval is not "a worse answer", it is "read the whole library every time".

**Why map-reduce rather than one enormous prompt.** Concatenating a whole corpus into a
single call fails in two ways that matter here: it exceeds the context window on any
realistic document set, and when it does not, the model attends unevenly and the
resulting summary is quietly dominated by whatever happened to be first. Summarising
per document and then combining keeps every document represented, and — the reason it
is worth the extra calls in a teaching tool — makes the shape visible in the trace: one
step per document, then one that joins them.

**It is the most expensive thing a student can run after Compare**, because cost scales
with the corpus rather than with the question. Hence the chunk bound below and the cap
check the Backend performs before dispatching.
"""

from __future__ import annotations

from collections.abc import Sequence

from ai_backend.agents.spend import QuerySpend
from ai_backend.contracts.models import (
    Chunk,
    Citation,
    Message,
    Role,
    SourceKind,
    StepType,
    Usage,
)
from ai_backend.contracts.pipeline import QueryBudget
from ai_backend.contracts.providers import LLMProvider
from ai_backend.errors import BudgetExceededError
from ai_backend.observability.trace import atrace_step
from ai_backend.retrievers.store import VectorStore

MAX_PER_DOCUMENT_TOKENS = 400
MAX_OVERVIEW_TOKENS = 700

# Chunks read per document. A bound rather than the whole document, because a 200-page
# PDF would otherwise put its entire text into one prompt and undo the reason for
# map-reducing in the first place. Chunks are taken in document order, so this reads
# the opening of a long document rather than an arbitrary slice — which is where a
# document says what it is about.
MAX_CHUNKS_PER_DOCUMENT = 12

# Documents summarised. A session holds at most five (PRD Section 6), so this is a
# backstop against a future limit change rather than a live constraint — but an
# unbounded loop over a corpus is exactly how a cost cap gets discovered the hard way.
MAX_DOCUMENTS = 10

_PER_DOCUMENT_PROMPT = """You summarise one document so a reader can tell what it \
covers and decide whether to ask about it.

Three or four sentences. State what kind of document it is, the specific topics it \
covers, and any concrete figures, dates, or named rules it contains — those are what \
someone will search for later.

Use only what the text says. Do not speculate about what else the document might \
contain. No preamble, no headings."""

_OVERVIEW_PROMPT = """You combine per-document summaries into one overview of a \
document set.

Structure it as: one sentence saying what this set of documents is, then one short \
paragraph per document, then one sentence on what the set as a whole would let someone \
answer.

Refer to each document by the filename given. Do not merge two documents into one \
paragraph and do not invent connections between them that the summaries do not \
support."""

EMPTY_SUMMARY = (
    "There is nothing indexed yet, so there is nothing to summarise. Upload a "
    "document, or load the demo set, and ask again."
)

# A selection that matched nothing indexed. Distinct from `EMPTY_SUMMARY` on purpose:
# "there is nothing indexed" and "none of the documents you picked have anything
# indexed" send a student to two different places, and the second is what they see
# after choosing a document whose upload failed. Neither costs an LLM call.
NOTHING_SELECTED = (
    "None of the selected documents have anything indexed, so there is nothing to "
    "summarise. Choose a document that finished indexing."
)


class Summary:
    """The overview, its per-document parts, and what it cost.

    A plain class rather than a `contracts` model: it does not cross the layer
    boundary as a shape the Backend reasons about — `backend/api/v1/summarize.py`
    reads three fields off it and builds its own response schema, exactly as it does
    for `Answer`.
    """

    __slots__ = ("text", "citations", "usage", "documents")

    def __init__(
        self,
        *,
        text: str,
        citations: list[Citation],
        usage: Usage,
        documents: int,
    ) -> None:
        self.text = text
        self.citations = citations
        self.usage = usage
        self.documents = documents


async def summarize_session(
    *,
    session_id: str,
    store: VectorStore,
    llm: LLMProvider,
    budget: QueryBudget,
    filenames: dict[str, str] | None = None,
    document_ids: Sequence[str] | None = None,
) -> Summary:
    """Summarise the session's indexed documents, or a chosen subset of them.

    `filenames` maps `document_id` → filename, passed in because the AI Backend does
    not own document names — the Backend's `document` table does (System Design
    Section 7). Absent, documents are referred to by a short id, which is worse for a
    reader but never wrong.

    `document_ids` narrows what is read. `None` means everything indexed, which is what
    every caller meant before the Summarize page offered a choice. It is a filter over
    ids the session's own store already returned, so an id that belongs to nobody, or
    to another session, simply matches nothing — it cannot reach across sessions.

    **An empty selection is not "everything".** It reads as a request for nothing and
    is refused without an LLM call. The other reading would make a request that named
    no documents run the most expensive action available over the whole corpus, which
    is the wrong way round for the one operation whose cost scales with the upload.
    """
    chunks = await store.all_chunks(session_id=session_id)
    if not chunks:
        # No LLM call. Asking a model to summarise nothing produces a confident
        # description of an empty set, which is the same failure mode as answering a
        # question from no context — and the reason the query pipelines refuse too.
        return Summary(text=EMPTY_SUMMARY, citations=[], usage=Usage(), documents=0)

    by_document = _group(chunks)
    if document_ids is not None:
        wanted = set(document_ids)
        by_document = {k: v for k, v in by_document.items() if k in wanted}
        if not by_document:
            return Summary(
                text=NOTHING_SELECTED, citations=[], usage=Usage(), documents=0
            )

    spend = QuerySpend(budget, llm=llm)

    parts: list[tuple[str, str]] = []
    citations: list[Citation] = []
    selected = list(by_document.items())[:MAX_DOCUMENTS]
    skipped = 0

    for document_id, document_chunks in selected:
        # **The combining call is always held in reserve.** Mapping until the budget
        # is empty would produce a run that paid for N document summaries and then
        # could not join them — strictly worse than summarising fewer documents, and
        # the failure would read as a budget bug rather than a deliberate stop. Same
        # reasoning as the ReAct loop's `_may_explore`.
        if spend.llm_calls >= budget.max_llm_calls - 1:
            skipped = len(selected) - len(parts)
            break

        name = (filenames or {}).get(document_id) or f"document {document_id[:8]}"
        try:
            text = await _summarize_one(
                name=name,
                document_id=document_id,
                chunks=document_chunks[:MAX_CHUNKS_PER_DOCUMENT],
                llm=llm,
                spend=spend,
            )
        except BudgetExceededError:
            # Recorded on the step by `_summarize_one` and not re-raised. A summary
            # covering three of five documents and saying so is useful; a 429 after
            # paying for three is not. System Design Section 11 requires a budget stop
            # be visible and partial rather than fatal.
            skipped = len(selected) - len(parts)
            break

        parts.append((name, text))
        # One citation per document, pointing at where its summary was drawn from.
        # Not per sentence: a summary is a claim about the whole document, and
        # pretending otherwise would attach a precise location to an imprecise claim.
        citations.append(
            Citation(
                document_id=document_id,
                filename=name,
                source_location=document_chunks[0].source_location,
                quote=document_chunks[0].content[:280],
                kind=SourceKind.DOCUMENT,
            )
        )

    if not parts:
        # The budget did not stretch to a single document. Reported as a refusal
        # rather than an empty overview, and it cost nothing.
        return Summary(
            text=(
                "There was not enough of this session's allowance left to summarise "
                "even one document. Start a new session, or ask a question instead — "
                "a question reads only the passages that match it."
            ),
            citations=[],
            usage=spend.usage,
            documents=0,
        )

    overview = await _combine(parts, llm=llm, spend=spend, skipped=skipped)
    return Summary(
        text=overview,
        citations=citations,
        usage=spend.usage,
        documents=len(parts),
    )


async def _summarize_one(
    *,
    name: str,
    document_id: str,
    chunks: list[Chunk],
    llm: LLMProvider,
    spend: QuerySpend,
) -> str:
    """The map half. One LLM call per document, traced separately.

    Separately on purpose: the per-document steps are where most of a summary's cost
    goes, and a single collapsed step would show the total without showing that it
    scales with the number of documents — which is the whole contrast with retrieval.
    """
    body = "\n\n".join(c.content for c in chunks)
    messages = [
        Message(role=Role.SYSTEM, content=_PER_DOCUMENT_PROMPT),
        Message(role=Role.USER, content=f"Filename: {name}\n\n{body}"),
    ]

    async with atrace_step(
        StepType.SUMMARIZE,
        label="Summarizer.document",
        raw_input=name,
        attributes={
            "document_id": document_id,
            "filename": name,
            "chunks_read": len(chunks),
        },
    ) as step:
        try:
            spend.reserve_for(messages, max_completion_tokens=MAX_PER_DOCUMENT_TOKENS)
        except BudgetExceededError as exc:
            # Recorded here, handled by the caller. The step has to carry the stop, or
            # the trace shows a summary that simply omitted a document with no reason
            # given — which reads as a bug rather than as a bounded run.
            step.mark_budget_exceeded(exc.message)
            step.set_output(f"Stopped: {exc.message}")
            raise

        completion = await llm.complete(
            messages, max_tokens=MAX_PER_DOCUMENT_TOKENS, temperature=0.0
        )
        spend.record(completion.usage)
        step.add_usage(completion.usage)
        step.set_output(completion.text)
        return completion.text.strip()


async def _combine(
    parts: list[tuple[str, str]],
    *,
    llm: LLMProvider,
    spend: QuerySpend,
    skipped: int = 0,
) -> str:
    """The reduce half. One call over the per-document summaries.

    `skipped` is stated in the output rather than left implicit. A summary that
    silently covers three of five documents is worse than no summary: a student would
    read it as a description of everything they uploaded.
    """
    joined = "\n\n".join(f"{name}:\n{text}" for name, text in parts)
    messages = [
        Message(role=Role.SYSTEM, content=_OVERVIEW_PROMPT),
        Message(role=Role.USER, content=joined),
    ]

    async with atrace_step(
        StepType.SUMMARIZE,
        label="Summarizer.overview",
        raw_input=f"{len(parts)} document summaries",
        attributes={
            "documents": len(parts),
            "combining": True,
            "documents_skipped": skipped,
        },
    ) as step:
        try:
            spend.reserve_for(messages, max_completion_tokens=MAX_OVERVIEW_TOKENS)
        except BudgetExceededError as exc:
            # The per-document summaries are already paid for, so returning them
            # unjoined is strictly better than discarding them — and far better than
            # a 429 that hands back nothing for money already spent. The loop above
            # reserves a call for this step precisely so this path is rare.
            step.mark_budget_exceeded(exc.message)
            step.set_output(f"Stopped before combining: {exc.message}")
            return _fallback_overview(parts, skipped=skipped, reason=exc.message)

        completion = await llm.complete(
            messages, max_tokens=MAX_OVERVIEW_TOKENS, temperature=0.0
        )
        spend.record(completion.usage)
        step.add_usage(completion.usage)
        step.set_output(completion.text)

        text = completion.text.strip()
        if skipped:
            text += (
                f"\n\nThis overview covers {len(parts)} document(s). "
                f"{skipped} more were not read — this session's allowance ran out "
                f"first. Summarizing reads everything, so its cost grows with how "
                f"much you upload."
            )
        return text


def _fallback_overview(
    parts: list[tuple[str, str]], *, skipped: int, reason: str
) -> str:
    """The per-document summaries, joined without a model.

    Plain concatenation rather than a second attempt at a cheaper call: there is no
    budget left, and the honest thing is to hand back exactly what was paid for and
    say why it is not a proper overview.
    """
    body = "\n\n".join(f"{name}: {text}" for name, text in parts)
    tail = (
        f" {skipped} document(s) were not read at all." if skipped else ""
    )
    return (
        f"Per-document summaries, not combined into an overview — {reason}{tail}\n\n"
        f"{body}"
    )


def _group(chunks: list[Chunk]) -> dict[str, list[Chunk]]:
    """Chunks per document, in the order they were indexed.

    Order matters: `MAX_CHUNKS_PER_DOCUMENT` truncates, and reading a document's
    opening is far more informative than reading an arbitrary slice of its middle.
    """
    grouped: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.document_id, []).append(chunk)
    return grouped


__all__ = ["EMPTY_SUMMARY", "NOTHING_SELECTED", "Summary", "summarize_session"]
