"""POST /api/v1/sessions/{id}/documents — upload up to 5 documents.

Milestone 0 delivers parsing and indexing. What is implemented *now* is the part
that is a Backend responsibility regardless of how ingestion works: the file
count, the size, the extension, and the "limit reached" refusal. Those are
validation and rate limiting, which System Design Section 6.1 places squarely in
this layer, and PRD Section 6 pins down precisely:

    Given a 6th file is uploaded to a session already holding 5, when the upload
    is submitted, then it is rejected with a clear "limit reached" message and no
    partial state change.

"No partial state change" is why the whole batch is validated before anything is
written. Validating file-by-file as each is stored would leave the first few
persisted when the batch is refused — a plausible implementation that fails the
criterion.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from ai_backend.config.settings import Settings
from ai_backend.errors import AxisError
from backend import dispatch
from backend.core.auth import require_matching_session
from backend.core.errors import UploadLimitError, ValidationError
from backend.dispatch import CORPORA, DEFAULT_CORPUS, DEMO_CORPUS, index_scope
from backend.schemas.query import DocumentStatus, UploadResponse
from backend.store.repositories import SessionRecord

router = APIRouter(tags=["documents"])


@router.post("/sessions/{session_id}/documents", response_model=UploadResponse)
async def upload_documents(
    session_id: str,
    request: Request,
    files: list[UploadFile] = File(...),
    # Bounded here for the same reason `QueryRequest.pace_ms` is: a browser-supplied
    # number that makes a request take longer belongs behind a ceiling at the edge.
    pace_ms: int = Form(0, ge=0, le=2000),
    # Which corpus these files join. Defaulted rather than required, so every existing
    # caller — the acceptance suite, `curl`, a student following the API docs — keeps
    # landing where a `QueryContext` with no corpus named looks.
    corpus: str = Form(DEFAULT_CORPUS),
    session: SessionRecord = Depends(require_matching_session),
) -> UploadResponse:
    settings: Settings = request.app.state.settings
    documents = request.app.state.documents
    limits = settings.upload
    # Narrowed to a known name before it reaches a scope. It arrives from a cookie via
    # a form field, and an open set would let a forged value address an arbitrary index
    # scope — empty, so harmless, but "nothing can name a scope we did not define" is
    # cheaper to hold than to reason about.
    corpus = corpus if corpus in CORPORA else DEFAULT_CORPUS

    existing = documents.count_for_corpus(session.id, corpus)
    if existing + len(files) > limits.max_files_per_session:
        # Refused whole, before a single row is written.
        #
        # **Per corpus, not per session**, which is the change that makes holding both
        # possible: the demo set is exactly `max_files_per_session` files, so a
        # session-wide count made this true for any existing document and one upload
        # permanently blocked the demo corpus.
        raise UploadLimitError(
            f"Limit reached: a corpus may hold {limits.max_files_per_session} "
            f"documents. This one already has {existing}, and you tried to "
            f"add {len(files)}.",
            detail=(
                "No files were stored. Clear this corpus, or switch to the other one "
                "— they have separate limits."
            ),
        )

    if not files:
        raise ValidationError("No files were included in the upload.")

    # Validate everything first, so a rejection leaves no partial state.
    for upload in files:
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in limits.allowed_extensions:
            raise ValidationError(
                f"{upload.filename!r} has an unsupported type ({suffix or 'none'}).",
                detail=f"Supported types: {', '.join(limits.allowed_extensions)}.",
            )
        if upload.size is not None and upload.size > limits.max_bytes_per_file:
            raise ValidationError(
                f"{upload.filename!r} is {upload.size} bytes, over the "
                f"{limits.max_bytes_per_file}-byte limit.",
            )

    ai = request.app.state.ai
    if ai is None:
        raise ValidationError(
            "Axis cannot index documents until its configuration is valid.",
            detail="Check /api/v1/health for what is wrong.",
        )

    named = [(upload.filename or "unnamed", await upload.read()) for upload in files]
    return await _index_batch(
        named,
        session_id=session.id,
        documents=documents,
        ai=ai,
        limits=limits,
        corpus=corpus,
        pace_ms=pace_ms,
    )


async def _index_batch(
    named: list[tuple[str, bytes]],
    *,
    session_id: str,
    documents,
    ai,
    limits,
    corpus: str = DEFAULT_CORPUS,
    pace_ms: int = 0,
) -> UploadResponse:
    """Record and index a batch whose bytes are already in hand.

    Extracted so the demo-document route below indexes through *exactly* this
    path. A second loop would be the obvious way to write that route and the wrong
    one: per-file failure handling, the real-length size recheck, and the
    pending→ready status transitions would then exist twice and would drift, and
    the demo set — the corpus the whole class watches — would be the copy nobody
    tested.
    """
    def _partial_note(result) -> str | None:
        """"This indexed, but not all of it" — said plainly, or not at all.

        The case that motivated it: a twenty-page scan with a typed cover sheet. One
        page has a text layer, nineteen do not, and the parser's all-or-nothing guard
        only fires when *nothing* is readable — so it indexed one page, reported ready,
        and said nothing. Every question it then could not answer looked like a
        retrieval bug.

        Names OCR, because that is the actual remedy and the student has no way to
        guess that a page which looks like text to them is a picture to Axis.
        """
        if not result.unreadable_blocks:
            return None
        total = result.block_count + result.unreadable_blocks
        return (
            f"{result.unreadable_blocks} of {total} pages had no text layer and were "
            f"skipped — they need OCR, which Axis does not do. Only the "
            f"{result.block_count} readable page(s) are searchable."
        )

    results: list[DocumentStatus] = []
    for filename, data in named:
        suffix = Path(filename).suffix.lower()
        record = documents.add(
            session_id=session_id,
            filename=filename,
            fmt=suffix.lstrip("."),
            # The declared size can be absent or wrong; the bytes we actually read
            # cannot be.
            byte_size=len(data),
            status="pending",
            corpus=corpus,
        )

        # Re-checked against the real length, because the pre-flight validation
        # above could only consult the client's claim.
        if len(data) > limits.max_bytes_per_file:
            documents.set_status(
                record.id, status="failed", error="File is larger than the limit."
            )
            results.append(
                DocumentStatus(
                    document_id=record.id,
                    filename=record.filename,
                    status="failed",
                    error=(
                        f"{record.filename!r} is {len(data)} bytes, over the "
                        f"{limits.max_bytes_per_file}-byte limit."
                    ),
                )
            )
            continue

        try:
            result = await dispatch.ingest_document(
                ai,
                session_id=session_id,
                document_id=record.id,
                filename=record.filename,
                data=data,
                corpus=corpus,
                pace_ms=pace_ms,
            )
            documents.set_status(record.id, status="ready")
            # **The corpus changed, so every cached answer about it is suspect.**
            # A cached answer is an answer about a *particular* set of documents;
            # once another is indexed, "what does the contract say about payment"
            # may have a different right answer, and serving the stored one would
            # be the cache actively making the system wrong. Cheaper and more
            # obviously correct than working out which answers this document could
            # have changed — and a workshop indexes a handful of files, so the cost
            # of throwing the cache away is one re-run of anything already asked.
            #
            # This corpus's answers only. The other corpus did not change, so its
            # cached answers are still about the documents they were drawn from —
            # dropping them would charge for a re-run that could not differ.
            ai.invalidate_cache(index_scope(session_id, corpus))
            results.append(
                DocumentStatus(
                    document_id=record.id,
                    filename=record.filename,
                    status="ready",
                    chunk_count=result.chunk_count,
                    note=_partial_note(result),
                )
            )
        except AxisError as exc:
            # Per-file failure, per the criterion: one unreadable PDF among five
            # must not fail the other four. The reason travels back to the student,
            # so it has to be the human-readable `message`, not a traceback.
            #
            # `detail` goes with it. It is the half that says what to do about the
            # failure — for a scan, that Axis does no OCR and a text-based export will
            # work — and it was being written and then dropped here, so the student saw
            # the diagnosis and never the remedy.
            documents.set_status(record.id, status="failed", error=exc.message)
            results.append(
                DocumentStatus(
                    document_id=record.id,
                    filename=record.filename,
                    status="failed",
                    error=exc.message,
                    detail=exc.detail,
                )
            )

    return UploadResponse(
        documents=results,
        accepted=sum(1 for r in results if r.status == "ready"),
        rejected=sum(1 for r in results if r.status == "failed"),
    )


@router.post("/sessions/{session_id}/documents/demo", response_model=UploadResponse)
async def load_demo_documents(
    session_id: str,
    request: Request,
    pace_ms: int = Form(0, ge=0, le=2000),
    session: SessionRecord = Depends(require_matching_session),
) -> UploadResponse:
    """Index the demo corpus the labelled questions were measured against.

    **Why this is an endpoint and not a note in the README telling people to
    upload some files.** A predicted outcome is a claim about a specific corpus:
    "splitting this question finds a document the blended search misses" is only
    true of documents that make it true. Offering the labelled questions without a
    one-click way to index the corpus they were measured on would leave a student
    running predictions against their own unrelated PDFs and concluding the
    predictions are wrong.

    **It loads into the `demo` corpus, always**, and takes no corpus parameter. That
    is the whole point of naming the corpora rather than deriving them from filenames:
    the labelled questions are claims measured against *these five files*, so they have
    to be reachable as a set even when a student's own documents are the active corpus.
    Loading it no longer competes with an upload for the same five slots.

    The file-count limit is deliberately *not* bypassed — a second load into a corpus
    that already holds the set gets the same refusal as any other upload. `DELETE
    /sessions/{id}/corpus/demo` is how you make room, and it exists so that refusal is
    recoverable without discarding the session.
    """
    settings: Settings = request.app.state.settings
    documents = request.app.state.documents
    limits = settings.upload

    # Refused here as well as hidden in the sidebar, and the route is the half that
    # matters: the button is what a person clicks, but this is what spends the money.
    # A stale page, a bookmark or a second tab all reach it without the button.
    if not settings.demo.documents_enabled:
        raise ValidationError(
            "The demo corpus is turned off.",
            detail=(
                "Loading it indexes four documents through the configured embedding "
                "provider. Set AXIS_DEMO__DOCUMENTS_ENABLED=true to offer it."
            ),
        )

    demo = dispatch.demo_document_set()

    existing = documents.count_for_corpus(session.id, DEMO_CORPUS)
    if existing + len(demo) > limits.max_files_per_session:
        raise UploadLimitError(
            f"Limit reached: the demo set is {len(demo)} documents and a corpus "
            f"may hold {limits.max_files_per_session}. The demo corpus already has "
            f"{existing}.",
            detail="Clear the demo corpus to load it again.",
        )

    ai = request.app.state.ai
    if ai is None:
        raise ValidationError(
            "Axis cannot index documents until its configuration is valid.",
            detail="Check /api/v1/health for what is wrong.",
        )

    return await _index_batch(
        [(d.filename, d.data) for d in demo],
        session_id=session.id,
        documents=documents,
        ai=ai,
        limits=limits,
        corpus=DEMO_CORPUS,
        pace_ms=pace_ms,
    )


@router.get("/sessions/{session_id}/documents", response_model=list[DocumentStatus])
async def list_documents(
    session_id: str,
    request: Request,
    corpus: str | None = None,
    session: SessionRecord = Depends(require_matching_session),
) -> list[DocumentStatus]:
    """What this session holds, and whether each file is queryable.

    `?corpus=` narrows to one; omitting it lists every corpus. The Frontend passes the
    active one, because a document list showing files the active index cannot reach is
    a list of things that will not be found.
    """
    ai = request.app.state.ai
    name = corpus if corpus in CORPORA else None
    records = request.app.state.documents.list_for_session(session.id, corpus=name)

    # Chunk counts come from the vector index rather than the document table, so
    # the number reflects what retrieval can actually reach. One lookup per corpus
    # actually present, so a document is counted against the scope it was indexed into
    # — reading them all from one scope reported zero for everything in the other.
    counts: dict[str, int] = {}
    if ai is not None:
        for scope_name in sorted({r.corpus for r in records}):
            counts.update(await ai.chunk_counts(index_scope(session.id, scope_name)))

    return [
        DocumentStatus(
            document_id=r.id,
            filename=r.filename,
            status=r.status,
            error=r.error,
            chunk_count=counts.get(r.id, 0),
            corpus=r.corpus,
        )
        for r in records
    ]
