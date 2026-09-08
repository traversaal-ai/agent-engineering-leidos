"""`ingest_document` — the ingestion path: parse → chunk → embed → store.

Run once per document, before any question is asked, and what it produces is the one
index **both** strategies query (System Design Section 8). Parsing lives in its own
module and knows nothing about chunks, so that "what text is in this file" and "how
should it be cut up" stay separately testable.

**Each of the four stages is its own trace step, nested under one `INGEST` parent.**
That is the only reason this file changed: the work was always these four things,
but it happened inside a single opaque step, so the UI could report "12 chunks" and
nothing else. A student never saw a document become searchable.

The stages carry their actual data — the extracted blocks, the chunk text with its
overlap, the vectors, what went into the index — because a canvas that showed four
labelled boxes and no content would be a diagram of RAG rather than a demonstration
of it. Every payload here is bounded (see the `MAX_*_SHOWN` constants): enough to
teach from, small enough that a workshop's SQLite file stays reasonable.
"""

from __future__ import annotations

import logging

from ai_backend.contracts.models import Chunk, IngestionResult, StepType, Usage
from ai_backend.contracts.providers import EmbeddingProvider, VisionProvider
from ai_backend.errors import IngestionError
from ai_backend.ingestion.chunker import ChunkingConfig, chunk_blocks
from ai_backend.ingestion.parsers import ParsedBlock, ParseResult, parse
from ai_backend.ingestion.safety import assert_safe_archive
from ai_backend.observability.trace import atrace_step
from ai_backend.providers.base import vector_preview
from ai_backend.retrievers.store import VectorStore

logger = logging.getLogger("axis.ingestion")

# Embeddings are requested in batches. Providers cap request size, and one batch
# per chunk would multiply HTTP overhead across a hundred-chunk document.
EMBED_BATCH_SIZE = 64

# How much of each stage's data reaches the trace.
#
# Bounded because a 200-page PDF produces hundreds of chunks and the trace is
# written to SQLite, echoed by the evaluation CLI, and rendered into a page. The
# numbers are chosen for what a class can actually look at: nobody pages through
# forty chunks on a projector, and the fifth sample block has never taught anyone
# anything the second did not.
MAX_BLOCKS_SHOWN = 6
MAX_CHUNKS_SHOWN = 12
MAX_CHUNK_CHARS_SHOWN = 600
MAX_EMBED_SAMPLES = 3


async def ingest_document(
    *,
    document_id: str,
    filename: str,
    data: bytes,
    session_id: str,
    store: VectorStore,
    embeddings: EmbeddingProvider,
    vision: VisionProvider | None = None,
    max_uncompressed_bytes: int,
    chunking: ChunkingConfig | None = None,
    corpus: str = "",
) -> IngestionResult:
    """Parse, chunk, embed, and index one uploaded document.

    Raises `IngestionError` on anything that makes the file unusable. The Backend
    catches that per file, so PRD Section 6's "one unreadable file among five"
    case reports a reason for that file and indexes the other four.

    `corpus` is recorded on the `ingest` step and used for nothing else here —
    `session_id` is already the composed scope by the time it arrives. It is carried
    because the trace is where "which corpus is this document in?" has to be
    answerable: the canvas binds its indexing track from these steps and must not
    describe a document the active corpus cannot search, and a student reading the raw
    trace has no other way to tell two corpora apart.
    """
    attributes: dict[str, object] = {"document_id": document_id, "filename": filename}
    if corpus:
        attributes["corpus"] = corpus
    async with atrace_step(
        StepType.INGEST,
        label=f"ingest {filename}",
        raw_input=f"{filename} ({len(data)} bytes)",
        attributes=attributes,
    ) as step:
        # Before anything reads the bytes: an Office file is a zip archive, and a
        # bomb must be refused rather than parsed (Section 6.5, priority 3).
        assert_safe_archive(
            filename, data, max_uncompressed_bytes=max_uncompressed_bytes
        )

        parsed = await _parse_stage(filename, data, vision=vision)
        blocks = parsed.blocks
        chunks = await _chunk_stage(
            blocks, document_id=document_id, filename=filename, config=chunking
        )
        if not chunks:
            raise IngestionError(f"{filename!r} produced no indexable content.")

        total_usage = await _embed_and_store_stages(
            chunks,
            filename=filename,
            session_id=session_id,
            store=store,
            embeddings=embeddings,
        )

        modalities = sorted({c.modality for c in chunks})
        if total_usage is not None:
            step.add_usage(total_usage)
        step.set_attribute("chunk_count", len(chunks))
        step.set_attribute("modalities", [str(m) for m in modalities])
        step.set_output(
            f"{len(chunks)} chunks from {len(blocks)} blocks "
            f"({', '.join(str(m) for m in modalities)})"
        )

        return IngestionResult(
            document_id=document_id,
            filename=filename,
            chunk_count=len(chunks),
            modalities=list(modalities),
            cost_usd=float(total_usage.cost_usd) if total_usage else 0.0,
            # Carried out of the AI Backend so the Backend can put it on the document
            # and the Frontend can show it. A partial extraction that only appears in
            # the trace is one nobody reads until they already distrust the answers.
            unreadable_blocks=len(parsed.unreadable),
            block_count=len(blocks),
        )


# ── The four stages ───────────────────────────────────────────────────────────
#
# Each wraps work that already happened, adds no behaviour, and records what it
# produced. They are separate functions rather than inline `atrace_step` blocks so
# the ingestion flow above still reads as four named steps at a glance.


async def _parse_stage(
    filename: str, data: bytes, *, vision: VisionProvider | None
) -> ParseResult:
    """A file becomes addressable blocks — pages, slides, sheets, images.

    The first thing a student needs to see, because it is the step that makes the
    format irrelevant: a PDF, a spreadsheet and a PNG all arrive here and all leave
    as text with a location attached. Everything downstream works on blocks and has
    no idea what kind of file it came from.
    """
    async with atrace_step(
        StepType.PARSE,
        label="parse",
        raw_input=f"{filename} ({len(data)} bytes)",
        attributes={"filename": filename, "bytes": len(data)},
    ) as step:
        result = await parse(filename, data, vision=vision)
        blocks = result.blocks

        kinds = sorted({str(b.modality) for b in blocks})
        step.set_attribute("blocks", len(blocks))
        step.set_attribute("block_kinds", kinds)
        # What was *not* readable, on the step that read it. A page with no text layer
        # is invisible everywhere downstream — it produces no chunk, no vector and no
        # citation — so the only place it can be reported is here, where the count is
        # still known. Zero is recorded too: "0 skipped" is the evidence that a short
        # extraction was the document rather than the parser.
        step.set_attribute("unreadable_blocks", len(result.unreadable))
        if result.unreadable:
            step.set_attribute("unreadable_locations", result.unreadable[:MAX_BLOCKS_SHOWN])
        # A sample rather than all of them, with the location kept: the location is
        # what a citation will later point at, so seeing it appear here is what
        # makes a citation traceable rather than magic.
        step.set_attribute(
            "sample_blocks",
            [
                {
                    "location": b.source_location or "unknown location",
                    "modality": str(b.modality),
                    "chars": len(b.text),
                    "preview": b.text[:MAX_CHUNK_CHARS_SHOWN],
                }
                for b in blocks[:MAX_BLOCKS_SHOWN]
            ],
        )
        skipped = (
            f", {len(result.unreadable)} with no text layer skipped"
            if result.unreadable
            else ""
        )
        step.set_output(
            f"{len(blocks)} block(s) from {filename} "
            f"({', '.join(kinds) or 'none'}){skipped}"
        )
        return result


async def _chunk_stage(
    blocks: list[ParsedBlock],
    *,
    document_id: str,
    filename: str,
    config: ChunkingConfig | None,
) -> list[Chunk]:
    """Blocks become overlapping chunks.

    **Async despite `chunk_blocks` being synchronous**, purely so it can use
    `atrace_step`. The sync `trace_step` emits through `_emit_soon`, which schedules
    the write on the loop rather than awaiting it — so the chunk step arrived *after*
    embed and store, or after the run had finished entirely. On a canvas whose whole
    job is to show a document becoming vectors in order, a stage that appears out of
    sequence is worse than one that does not appear at all.

    The stage that most rewards being shown rather than described. The notebook
    teaches the trade-off in prose — "chunks that are too large dilute the meaning
    of the embedding, while chunks that are too small lose important surrounding
    context" — and a student who reads that has learned a sentence. A student who
    pages through the actual chunks, sees where one was cut and sees the same 150
    characters repeated at the start of the next, has learned what overlap is *for*.

    Hence `overlap_with_previous`: computed here rather than in the renderer,
    because the exact shared text depends on `_merge_and_overlap`'s word-boundary
    rule, and a client re-deriving it would drift from the chunker the first time
    that rule changed.
    """
    cfg = config or ChunkingConfig()
    async with atrace_step(
        StepType.CHUNK,
        label="chunk",
        raw_input=f"{len(blocks)} block(s)",
        # `filename` on every indexing stage, not just `parse`. Indexing runs once per
        # document and the canvas has one node per stage, so the pane offers the other
        # documents as siblings — and a chip labelled "5 block(s)" instead of
        # "handbook.pdf" is a chip nobody can choose between.
        attributes={
            "document_id": document_id,
            "filename": filename,
            "max_chars": cfg.max_chars,
            "overlap_chars": cfg.overlap_chars,
            "min_chars": cfg.min_chars,
        },
    ) as step:
        chunks = chunk_blocks(blocks, document_id=document_id, config=cfg)

        step.set_attribute("chunk_count", len(chunks))
        step.set_attribute("chunks_shown", min(len(chunks), MAX_CHUNKS_SHOWN))
        step.set_attribute(
            "chunks",
            [
                {
                    "index": index,
                    "chunk_id": chunk.id,
                    "location": chunk.source_location or "unknown location",
                    "chars": len(chunk.content),
                    "text": chunk.content[:MAX_CHUNK_CHARS_SHOWN],
                    "truncated": len(chunk.content) > MAX_CHUNK_CHARS_SHOWN,
                    "overlap_with_previous": _overlap(
                        chunks[index - 2].content if index >= 2 else "",
                        chunk.content,
                    ),
                }
                for index, chunk in enumerate(chunks[:MAX_CHUNKS_SHOWN], start=1)
            ],
        )
        step.set_output(
            f"{len(chunks)} chunk(s), up to {cfg.max_chars} chars with "
            f"{cfg.overlap_chars} of overlap"
        )
        return chunks


async def _embed_and_store_stages(
    chunks: list[Chunk],
    *,
    filename: str,
    session_id: str,
    store: VectorStore,
    embeddings: EmbeddingProvider,
) -> Usage | None:
    """Chunks become vectors, and the vectors go into the index.

    Two stages around one batch loop, which is why they share a function: the
    provider is called in batches for cost reasons, and splitting the loop in two
    to give each stage its own would double the number of round trips purely to
    make the trace tidier.

    Both stages are opened once around the whole loop rather than once per batch,
    so the canvas shows "embed" and "store" as single stages regardless of how many
    batches a large document needed. The per-batch provider calls still appear as
    their own nested `EMBED` steps for anyone reading the raw trace.
    """
    total_usage: Usage | None = None
    vectors_written = 0
    samples: list[dict[str, object]] = []
    dimensions = 0

    async with atrace_step(
        StepType.EMBED,
        label="embed",
        raw_input=f"{len(chunks)} chunk(s)",
        # Says what the embedding was *for*. The provider cannot know — it is handed
        # text and returns vectors — so the stage records it, and the query side
        # records `query` the same way. That both say "embed" is the point: it is
        # the same model and the same vector space, which is the fact that makes
        # retrieval work at all.
        attributes={
            "purpose": "index",
            "chunks": len(chunks),
            "filename": filename,
        },
    ) as embed_step:
        pending: list[tuple[list[Chunk], list[list[float]]]] = []

        for start in range(0, len(chunks), EMBED_BATCH_SIZE):
            batch = chunks[start : start + EMBED_BATCH_SIZE]
            embedded = await embeddings.embed([c.content for c in batch])
            if len(embedded.vectors) != len(batch):
                raise IngestionError(
                    f"The embedding provider returned {len(embedded.vectors)} "
                    f"vectors for {len(batch)} chunks of {filename!r}.",
                    detail="Indexing was abandoned rather than storing a partial document.",
                )
            pending.append((batch, embedded.vectors))
            total_usage = (
                embedded.usage if total_usage is None else total_usage + embedded.usage
            )

            # The pairing is the lesson: this text became these numbers. Taken from
            # the first batch only, because the fourth example of the same
            # transformation teaches nothing the first did not.
            for chunk, vector in zip(batch, embedded.vectors, strict=True):
                dimensions = dimensions or len(vector)
                if len(samples) < MAX_EMBED_SAMPLES:
                    samples.append(
                        {
                            "chunk_id": chunk.id,
                            "location": chunk.source_location or "unknown location",
                            "text": chunk.content[:MAX_CHUNK_CHARS_SHOWN],
                            **vector_preview(vector),
                        }
                    )

        if total_usage is not None:
            embed_step.add_usage(total_usage)
        embed_step.set_attribute("model", embeddings.model)
        embed_step.set_attribute("dimensions", dimensions)
        embed_step.set_attribute("samples", samples)
        embed_step.set_output(
            f"{len(chunks)} vector(s) of {dimensions} dimensions from "
            f"{embeddings.model}"
        )

    async with atrace_step(
        StepType.STORE,
        label="store",
        raw_input=f"{len(chunks)} vector(s)",
        attributes={"dimensions": dimensions, "filename": filename},
    ) as store_step:
        for batch, vectors in pending:
            await store.add(session_id=session_id, chunks=batch, vectors=vectors)
            vectors_written += len(vectors)

        # Read back rather than accumulated, so the number is what the index
        # actually holds — including everything indexed before this document. A
        # student watching the third upload should see the index growing, not four
        # separate counts of four.
        total = await store.count(session_id=session_id)
        store_step.set_attribute("written", vectors_written)
        store_step.set_attribute("total_in_index", total)
        store_step.set_output(
            f"{vectors_written} vector(s) written; the index now holds {total}"
        )

    return total_usage


def _overlap(previous: str, current: str) -> str:
    """The text `current` repeats from the end of `previous`.

    Found by matching the longest suffix of one against the prefix of the other,
    rather than by re-applying the chunker's overlap rule: `_merge_and_overlap`
    trims to a word boundary, so the shared text is rarely exactly
    `overlap_chars` long, and a renderer that assumed it was would highlight the
    wrong span.

    Empty for the first chunk, and for a chunk that begins a new block — blocks are
    never merged, so there is genuinely nothing shared, and showing "no overlap"
    there is itself informative.
    """
    if not previous or not current:
        return ""
    limit = min(len(previous), len(current))
    for size in range(limit, 0, -1):
        if previous[-size:] == current[:size]:
            return current[:size]
    return ""
