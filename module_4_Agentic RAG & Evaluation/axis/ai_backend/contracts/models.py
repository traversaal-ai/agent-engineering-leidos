"""The stable vocabulary shared by all three layers.

Everything here is a data shape, not behaviour. It is deliberately the first
module written in the project: the Frontend renders against `AgentStep`, the
Backend persists it, the evaluation harness scores it, and both strategies
emit it identically. Defining it before any pipeline exists is what makes the
two strategies comparable rather than two separately-instrumented systems
(System Design Section 7).
"""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def new_id() -> str:
    return uuid.uuid4().hex


def utc_now() -> datetime:
    return datetime.now(UTC)


# Strictly increasing, assigned when a step is created. This is what the trace is
# ordered by — *not* `started_at`.
#
# Wall-clock is not good enough, and the reason is platform-specific enough to be
# worth recording. On Windows `datetime.now()` resolves to roughly 1–15 ms, which
# is coarser than these steps take: a retrieval and the embedding call inside it
# were observed with byte-identical timestamps. Ordering then fell through to the
# database rowid, which is *insertion* order — and since a step is written when it
# completes, the child was inserted first and rendered above its own parent.
#
# A counter sidesteps clock resolution entirely. Process-local, which is all that
# is needed: a trace never spans processes.
_seq = itertools.count(1)


def next_seq() -> int:
    return next(_seq)


class Strategy(StrEnum):
    """The two pipelines Axis compares — System Design Section 9.

    One variable, and it is orchestration: both read the same vector index over the same
    documents, so a difference between them is attributable to the router, decomposer,
    rewriter, cache and loop that only one of them has.

    An enum rather than a pair of strings because the value is persisted in
    `agent_step.strategy` and `query_run.strategy`, validated on the way in from a request
    body, and used as a dict key by the pipeline registry. Two members is still worth a
    type.

    **Was four.** `lightrag` and `agentic_lightrag` filled a graph-retrieval column that
    was specified and never built; it is a non-goal now, not deferred work (PRD Section 3).
    Do not add a member for a pipeline that does not exist — an unregistered `Strategy` is
    a 501 that reads like a bug.
    """

    NAIVE_RAG = "naive_rag"
    AGENTIC_RAG = "agentic_rag"

    @property
    def is_agentic(self) -> bool:
        return self is Strategy.AGENTIC_RAG


class StepType(StrEnum):
    """The step kinds named in PRD Section 6's live-trace criterion.

    `INGEST`, `EMBED`, and `GENERATE` are not in that list but are traced too —
    the criterion sets a floor on what must be visible, not a ceiling.

    **The four mechanism steps — `PARSE`, `CHUNK`, `STORE`, `AUGMENT` — exist so a
    student can watch RAG happen rather than be told about it.** Each was previously
    real work happening inside another step: parsing, chunking and storing inside
    `INGEST`, prompt assembly inside `SYNTHESIZE`. Nothing about the pipeline changed
    when they were added; what changed is that the canvas can now show a document
    becoming vectors and a question finding them, which is the whole shape of
    retrieval-augmented generation and was previously invisible.
    """

    # ── Phase A: indexing, once per document ──────────────────────────────
    PARSE = "parse"
    CHUNK = "chunk"
    STORE = "store"

    # ── Phase B: query, once per question ─────────────────────────────────
    # Resolving the question before anything is embedded. Its own step because it
    # is the only place a follow-up can be repaired: "How long is it?" does not
    # retrieve badly, it retrieves *nothing*, and no rephrasing of those four words
    # recovers what "it" was. A student sees the question they typed and the
    # question the system actually searched for, side by side.
    REWRITE = "rewrite"
    # Asking whether this question has already been answered. First in the query
    # phase, and the only step that can make every step after it *absent* — a hit
    # returns the stored answer and the pipeline is never entered. That absence is
    # load-bearing in exactly the way `route`'s absence is on a naive run: the
    # canvas greys the answering track out rather than drawing stages that did not
    # happen.
    CACHE_LOOKUP = "cache_lookup"
    ROUTE = "route"
    DECOMPOSE = "decompose"
    RETRIEVE = "retrieve"
    # Assembling the prompt: system rules, the numbered passages, the question.
    # Its own step because it is the moment "retrieval-augmented" means something —
    # a student who never sees the assembled prompt has not seen what augmentation
    # *is*, and it was previously built inline and thrown away.
    AUGMENT = "augment"
    # A web search. Its own type rather than folded into RETRIEVE, because the two
    # differ in every way a student needs to see: one is a local similarity search
    # over their own material, the other is a paid call to a third party returning
    # text nobody vetted. A canvas that drew them identically would erase the
    # distinction PRD Section 6 requires be obvious.
    SEARCH_WEB = "search_web"
    # Map-reduce over the whole corpus. Two step types would be over-modelling — the
    # `document_id` attribute distinguishes a per-document pass from the combining
    # one, and the canvas reads that rather than a second enum member.
    SUMMARIZE = "summarize"
    CALL_TOOL = "call_tool"
    SYNTHESIZE = "synthesize"
    INGEST = "ingest"
    EMBED = "embed"
    GENERATE = "generate"
    NARRATE = "narrate"
    # One turn of the ReAct loop: the model deciding what to do next. Its tool
    # calls nest underneath it, which is what turns an agentic trace into a tree
    # a student can read the cost off (Section 7, `parent_step_id`).
    ITERATE = "iterate"


class StepStatus(StrEnum):
    """Why this is an enum and not a boolean:

    System Design Section 11 requires failures be *visible* in the trace rather
    than silent. `BUDGET_EXCEEDED` is distinct from `ERROR` because "the agent
    stopped because we told it to" is a different lesson from "the agent broke",
    and students need to tell them apart at a glance.

    `RUNNING` is the one that is not an outcome. A step used to be written only
    when it *finished*, so the trace carried no "started" signal and the canvas
    had to guess which stage was in flight — it marked the next pending one and
    hoped. A student watching an upload therefore saw a jump from nothing to
    everything rather than a process. Emitting the step on entry and again on
    exit, under the same id, turns that guess into a measurement.
    """

    RUNNING = "running"
    OK = "ok"
    ERROR = "error"
    BUDGET_EXCEEDED = "budget_exceeded"


class Usage(BaseModel):
    """Token and cost accounting for a single external call.

    `cost_usd` is always computed by Axis from its own pricing table
    (`ai_backend/providers/pricing.py`), never read from a vendor response.
    Vendors report usage, not price, and a wrong price silently breaks the
    per-session cap.
    """

    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: Decimal = Decimal("0")

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )


EMPTY_USAGE = Usage()


class AgentStep(BaseModel):
    """One recorded unit of a trace.

    The backbone of the trace viewer, the Compare dashboard, and the evaluation
    harness. See System Design Section 7 for why `parent_step_id`, `status`, the
    token fields, and `raw_input` each earn their place.
    """

    id: str = Field(default_factory=new_id)
    # Creation order within this process. The trace is sorted by this rather than
    # by `started_at` — see the note on `next_seq` for why wall-clock is not
    # sufficient.
    seq: int = Field(default_factory=next_seq)
    session_id: str
    trace_id: str
    # Present iff this step happened inside another. Makes the trace a tree, so
    # a ReAct iteration's retrievals and tool calls nest under that iteration.
    parent_step_id: str | None = None
    step_type: StepType
    status: StepStatus = StepStatus.OK
    # Which strategy produced this step. Set on every step so a ComparisonRun can
    # slice one trace store by strategy.
    strategy: Strategy | None = None
    label: str = ""

    raw_input: str | None = None
    raw_output: str | None = None
    # Populated lazily, and only if a student asks for the narrated view — the
    # LLM cost of narration is paid on demand, then cached (PRD Section 6).
    narration: str | None = None

    started_at: datetime = Field(default_factory=utc_now)
    duration_ms: int = 0
    usage: Usage = EMPTY_USAGE
    error: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolSpec(BaseModel):
    """A provider-neutral tool declaration.

    OpenAI and Anthropic describe tools differently. Translating happens inside
    each adapter, so the ReAct loop built at Milestone 1 never branches on which
    provider is configured.
    """

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    role: Role
    content: str
    # Set when role is TOOL, tying a result back to the call that requested it.
    tool_call_id: str | None = None
    name: str | None = None
    # Set when role is ASSISTANT and that turn requested tools. Required to replay
    # a tool exchange back to a provider: both OpenAI and Anthropic reject a tool
    # result that is not preceded by the assistant turn which asked for it.
    #
    # Added at Milestone 1, when the ReAct loop needed a second turn. Worth noting
    # how this would have failed without it: the fake provider ignores the message
    # list entirely, so a loop that appended only the `TOOL` message would pass
    # every offline test and 400 against the real API — the same shape as two
    # defects already found by running the app rather than the suite.
    tool_calls: list[ToolCall] = Field(default_factory=list)


class FinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    OTHER = "other"


class Completion(BaseModel):
    text: str
    model: str
    usage: Usage = EMPTY_USAGE
    finish_reason: FinishReason = FinishReason.STOP
    tool_calls: list[ToolCall] = Field(default_factory=list)


class CompletionChunk(BaseModel):
    """One increment of a streamed completion. The final chunk carries usage."""

    text: str = ""
    usage: Usage | None = None
    finish_reason: FinishReason | None = None


class EmbeddingResult(BaseModel):
    vectors: list[list[float]]
    model: str
    usage: Usage = EMPTY_USAGE


class Caption(BaseModel):
    """A text description of an image, produced at ingestion time.

    Carries its own `Usage` because captioning is a real LLM call. An upload of
    five slide decks full of diagrams can cost more than the queries that follow,
    and that cost belongs on the ingestion step where a student can see it rather
    than buried in a total.
    """

    text: str
    model: str
    usage: Usage = EMPTY_USAGE


class Modality(StrEnum):
    """Images and tables are captioned to text before embedding (System Design
    Section 10), but the original modality is retained so the trace can show a
    student that an answer came from a diagram rather than prose.
    """

    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"


class Document(BaseModel):
    id: str = Field(default_factory=new_id)
    filename: str
    format: str
    upload_time: datetime = Field(default_factory=utc_now)
    byte_size: int = 0


class Chunk(BaseModel):
    id: str = Field(default_factory=new_id)
    document_id: str
    content: str
    modality: Modality = Modality.TEXT
    # Human-meaningful origin, e.g. "p. 4" or "Sheet1!B2:F19". This is what a
    # citation shows a student so they can go and check it.
    source_location: str = ""
    score: float | None = None


class IngestionResult(BaseModel):
    """The outcome of indexing one document.

    Lives in `contracts` rather than in the ingestion package because it crosses
    the layer boundary: the Backend receives one of these and turns it into an
    upload response. Anything that travels between layers is part of the contract
    by definition, and keeping it here means `backend/` never imports the
    ingestion implementation to name its return type.
    """

    document_id: str
    filename: str
    chunk_count: int
    modalities: list[Modality] = Field(default_factory=list)
    cost_usd: float = 0.0
    # How many addressable pieces the parser found, and how many of those held no
    # text. A page in a scanned PDF is invisible everywhere downstream — no chunk, no
    # vector, no citation — so without these a twenty-page scan with a typed cover
    # sheet indexes one page, reports "ready", and every answer it cannot support
    # looks like a retrieval bug rather than a missing text layer.
    block_count: int = 0
    unreadable_blocks: int = 0


class SourceKind(StrEnum):
    """Where a cited passage came from.

    Exists because PRD Section 6 requires a student never mistake "my documents said
    this" for "a search result said this". Before the web route the distinction was
    guaranteed by construction — there was only one kind — and the criterion could be
    silent about it. Now it has to be carried, and carried as an enum rather than
    inferred from `url` being non-empty: an inference is something a renderer can
    forget to make, and the failure would be a web citation that looks like a
    document one.
    """

    DOCUMENT = "document"
    WEB = "web"


class WebSource(BaseModel):
    """One web search result, as the provider returned it.

    Deliberately just the three fields a search API's result list gives: there is no
    `content`, because Axis never fetches the page. The snippet is all there is, and
    modelling more would invite a future change that quietly starts following links —
    which is the SSRF boundary in System Design Section 6.5.
    """

    title: str = ""
    url: str = ""
    snippet: str = ""


class SearchResult(BaseModel):
    """What a `SearchProvider` returns.

    Carries `usage` for the same reason `Completion` and `EmbeddingResult` do: the
    call cost money and the cost has to reach the session ledger. Search is priced
    per call rather than per token, so `prompt_tokens` stays zero and `cost_usd` is
    the flat rate — see `providers/pricing.py`. Reporting zero here would make the
    web route look free in the one table built to compare costs.
    """

    sources: list[WebSource] = Field(default_factory=list)
    usage: Usage = EMPTY_USAGE


class Citation(BaseModel):
    """One attributable source behind an answer.

    `document_id`/`filename` are populated for a document citation and empty for a web
    one; `url` the other way round. Both kinds carry `quote`, because the point of a
    citation here is that a student can check it.
    """

    document_id: str = ""
    filename: str = ""
    source_location: str = ""
    quote: str = ""
    kind: SourceKind = SourceKind.DOCUMENT
    # Populated only for `kind == WEB`. Shown to the student; never requested by Axis.
    url: str = ""


class RetrievedContext(BaseModel):
    """What every `Retriever` returns.

    `sources` is filled by web search and by no retriever. Web results are deliberately
    *not* squeezed into `chunks` — a `Chunk` carries a `document_id`, and inventing one
    for a search result would put a fake document id into the citation model, the trace,
    and the evaluation harness's document-recall scoring, all of which key on it meaning
    something.

    **Two fields were removed here.** `entities` and `relations` existed for a graph
    retriever that was never built: nothing ever populated them, and four separate code
    paths merged two permanently-empty lists. Adding a field for a hypothetical
    implementation costs every real caller a branch it can never take.
    """

    chunks: list[Chunk] = Field(default_factory=list)
    sources: list[WebSource] = Field(default_factory=list)
    usage: Usage = EMPTY_USAGE

    @property
    def is_empty(self) -> bool:
        # `sources` counts. A web-only retrieval has no chunks, and treating that as
        # empty would send the pipeline down the ungrounded path — refusing to answer
        # while holding the material to answer with.
        return not (self.chunks or self.sources)


class Answer(BaseModel):
    """The result of running one strategy against one question.

    `citations` may be empty only when `grounded` is False — the answer must then
    say plainly that nothing relevant was found rather than inventing a source
    (PRD Section 6, citations criterion).
    """

    text: str
    strategy: Strategy
    trace_id: str
    citations: list[Citation] = Field(default_factory=list)
    grounded: bool = True
    usage: Usage = EMPTY_USAGE
    latency_ms: int = 0
