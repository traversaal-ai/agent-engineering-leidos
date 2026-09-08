"""Query request and response.

The response carries `citations`, `cost_usd`, and `latency_ms` alongside the
answer text because those three are the comparison — an answer without its cost
and latency is exactly the abstraction the platform exists to replace.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ai_backend.contracts.models import Strategy
from ai_backend.contracts.pipeline import DEFAULT_CORPUS


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    strategy: Strategy
    # Which of the session's corpora to search. Validated against the closed set in
    # `run_query` rather than here, so an unrecognised name falls back to the empty
    # corpus instead of 422-ing a student out of a run.
    corpus: str = DEFAULT_CORPUS
    # Milliseconds to hold before each stage the canvas draws, so a class can follow
    # a run that would otherwise finish faster than anyone can watch.
    #
    # **Bounded here, at the boundary**, because this is a number supplied by a
    # browser that makes a request take longer — the one shape of input where an
    # unbounded value is a way to tie up a worker. Nine stages at the ceiling is
    # eighteen seconds, which is a slow demo and not an outage.
    #
    # It never touches a measurement: the pause happens between stages, and every
    # `duration_ms`, token count and cost is timed across the work alone. See
    # `_pause_for` in `ai_backend/observability/trace.py`.
    pace_ms: int = Field(default=0, ge=0, le=2000)
    # Whether this query may leave the uploaded documents.
    #
    # **Permission, not capability**, and the distinction is the security property:
    # whether a search provider exists is `AXIS_SEARCH__PROVIDER`, read server-side at
    # startup, and this is combined with it using `and`. So `true` from a browser
    # cannot reach the internet on an install that configured no provider — it can only
    # decline one that was.
    #
    # Defaults to `False`. A web call is paid, goes to a third party, and carries the
    # prompt-injection exposure of System Design Section 6.5; configuring a provider
    # makes the route available, and asking for it is a separate act. A client that
    # omits the field therefore gets the documents-only behaviour, which is the safe
    # direction for a field to be forgotten in.
    web_search: bool = False

    # Whether this query may be answered from the semantic cache.
    #
    # Capability-and-permission again, but note the default runs the *other* way
    # from `web_search` above, and deliberately: a web call spends money at a third
    # party, where a cache hit only ever avoids spending. So a client omitting this
    # field gets the cache, and the safe direction for *this* field to be forgotten
    # in is on. An instructor switches it off to charge full price for a question
    # the class has already asked.
    cache: bool = True


class CitationOut(BaseModel):
    """One citation, on the wire.

    `kind` is what PRD Section 6's distinguishability criterion rests on: a student
    must never mistake "my documents said this" for "a search result said this". It
    travels as an explicit field rather than being inferred from `url` being
    non-empty, because an inference is something a renderer can forget to make and
    the failure would be a web citation drawn as a document one.
    """

    document_id: str = ""
    filename: str = ""
    source_location: str = ""
    quote: str = ""
    # "document" or "web".
    kind: str = "document"
    # Set only for a web citation. Shown to the student; never fetched by Axis.
    url: str = ""


class QueryResponse(BaseModel):
    answer: str
    strategy: Strategy
    # The handle for GET /sessions/{id}/trace — how the Frontend ties this answer
    # to the steps that produced it.
    trace_id: str
    citations: list[CitationOut] = Field(default_factory=list)
    # False when nothing relevant was found. The answer then says so plainly
    # rather than inventing a citation (PRD Section 6).
    grounded: bool = True
    latency_ms: int = 0
    cost_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class DocumentStatus(BaseModel):
    """Per-file upload outcome.

    PRD Section 6 requires each file be confirmed individually with a success or
    a failure reason, so one unreadable PDF among five does not fail the batch.
    """

    document_id: str | None = None
    filename: str
    status: str  # "pending" | "ready" | "failed"
    error: str | None = None
    # The actionable half of a failure — `AxisError.detail`. "No readable text was
    # found in 'scan.pdf'" is the diagnosis; "a scanned PDF needs OCR, which Axis does
    # not do — try exporting a text-based version" is what the student can act on, and
    # it used to be written, travel as far as the API payload, and stop there.
    detail: str | None = None
    # A document that indexed and lost something. Distinct from `error`, which means
    # nothing was indexed at all: this one is retrievable, just not in full.
    #
    # Set by the upload routes only, not by `GET /documents`. Page counts are not in the
    # `document` table and adding a column would mean a non-idempotent `ALTER TABLE`,
    # which the migration rule in `store/db.py` rules out. The durable record is the
    # parse step's `unreadable_blocks` attribute — which is what the canvas draws and
    # the raw trace keeps, so the finding survives the flash without a second copy of
    # it in the schema.
    note: str | None = None
    # How many chunks the document produced. Zero on a file that parsed but
    # yielded nothing indexable — which a student needs to see, because such a
    # document is visible in the list yet unreachable by retrieval.
    chunk_count: int = 0
    # Which corpus this document is in — `demo` or `mine`.
    #
    # Reported rather than inferred. The Frontend used to tell the demo set apart by
    # comparing filenames against `/demo/questions`'s list, which is adequate as a gate
    # and wrong as an identity: nothing stops a student uploading a file called
    # `acme-msa-2026.md`, and from there the two would disagree about what they hold.
    corpus: str = DEFAULT_CORPUS


class UploadResponse(BaseModel):
    documents: list[DocumentStatus] = Field(default_factory=list)
    accepted: int = 0
    rejected: int = 0
