"""Recursive text chunking.

Written here rather than imported from LangChain, for the same reason the
observability library is hand-written: System Design Section 10 lists
semantic/recursive chunking as a deliberate choice over fixed-size, and the whole
point of that choice is lost if students cannot see what it does. It is about
sixty readable lines.

**Why recursive splitting beats fixed-size.** A fixed 800-character window cuts
mid-sentence, so a chunk begins with half a clause and the embedding of it means
something slightly different from the text it came from. Recursive splitting tries
the largest natural boundary first — paragraph, then sentence, then word — and only
cuts mid-word if a single word somehow exceeds the budget. Retrieval quality
improves because each chunk is a coherent thought.

**Why overlap.** A fact that straddles a boundary would otherwise be
unretrievable: the chunk with the question's keywords lacks the answer, and the
chunk with the answer lacks the keywords. Overlap costs storage and embedding
tokens to buy that back — a trade worth naming in class, since it is why an
identical corpus costs more to index at higher overlap.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from ai_backend.contracts.models import Chunk, Modality, new_id
from ai_backend.ingestion.parsers import ParsedBlock

# Tried in order, largest natural unit first.
_SEPARATORS: tuple[str, ...] = (
    "\n\n",  # paragraph
    "\n",  # line — the meaningful unit in a spreadsheet or slide
    ". ",  # sentence
    "; ",
    ", ",
    " ",  # word
)

_WHITESPACE = re.compile(r"[ \t]+")


class ChunkingConfig(BaseModel):
    """Chunk sizes are in characters, not tokens.

    Approximate against a real tokenizer, but it avoids a per-vendor tokenizer
    dependency and keeps chunking identical no matter which provider is
    configured — otherwise switching providers would silently re-shape the index
    and make two Compare runs incomparable.
    """

    max_chars: int = 1_200
    overlap_chars: int = 150
    # Below this, a fragment is merged into its neighbour instead of standing
    # alone: a 20-character chunk embeds to noise and pollutes retrieval.
    min_chars: int = 100


def chunk_blocks(
    blocks: list[ParsedBlock],
    *,
    document_id: str,
    config: ChunkingConfig | None = None,
) -> list[Chunk]:
    """Turn parsed blocks into embeddable chunks.

    Blocks are never merged across boundaries. Two PDF pages could be joined into
    one chunk to save tokens, but then the chunk spans "p. 4" and "p. 5" and its
    citation can only name one of them — so a student following the citation lands
    in the wrong place. Keeping the block boundary keeps citations honest.
    """
    cfg = config or ChunkingConfig()
    chunks: list[Chunk] = []

    for block in blocks:
        text = _normalise(block.text)
        if not text:
            continue

        # A table or an image caption is kept whole when it fits. Splitting a
        # table mid-row separates a value from its header, and the header is what
        # makes the value mean anything.
        if block.modality in (Modality.TABLE, Modality.IMAGE) and len(text) <= cfg.max_chars:
            pieces = [text]
        else:
            pieces = _split_recursive(text, cfg)

        total = len(pieces)
        for index, piece in enumerate(pieces, start=1):
            chunks.append(
                Chunk(
                    id=new_id(),
                    document_id=document_id,
                    content=piece,
                    modality=block.modality,
                    # A split block says which part, so a citation stays precise
                    # without pretending a 5-page span is one location.
                    source_location=(
                        block.source_location
                        if total == 1
                        else f"{block.source_location} ({index}/{total})"
                    ),
                )
            )
    return chunks


def _normalise(text: str) -> str:
    """Collapse runs of spaces and tabs, keep paragraph structure.

    Blank lines survive because they are the strongest split signal available;
    horizontal whitespace is just PDF extraction noise that would waste embedding
    tokens.
    """
    lines = [_WHITESPACE.sub(" ", line).strip() for line in text.splitlines()]
    out: list[str] = []
    for line in lines:
        # Never more than one blank line in a row.
        if not line and out and not out[-1]:
            continue
        out.append(line)
    return "\n".join(out).strip()


def _split_recursive(text: str, cfg: ChunkingConfig) -> list[str]:
    if len(text) <= cfg.max_chars:
        return [text]

    pieces = _split_on_best_separator(text, cfg.max_chars)
    return _merge_and_overlap(pieces, cfg)


def _split_on_best_separator(text: str, max_chars: int) -> list[str]:
    """Split at the largest natural boundary that actually helps.

    A separator is only useful if it produces at least one piece within budget;
    otherwise recurse to a finer one. The final fallback is a hard character cut,
    for pathological input such as a single 5,000-character token.
    """
    for separator in _SEPARATORS:
        if separator not in text:
            continue
        parts = [p for p in text.split(separator) if p.strip()]
        if len(parts) < 2:
            continue

        result: list[str] = []
        for part in parts:
            if len(part) <= max_chars:
                result.append(part)
            else:
                # This part is still too big — try a finer separator on it alone.
                result.extend(_split_on_best_separator(part, max_chars))
        return result

    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def _merge_and_overlap(pieces: list[str], cfg: ChunkingConfig) -> list[str]:
    """Pack pieces up to the budget, then add the trailing overlap.

    Two passes rather than one, because overlap has to be applied to final chunk
    boundaries. Applied during packing it would compound — each chunk inheriting
    the previous chunk's inherited tail.
    """
    packed: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current} {piece}".strip() if current else piece
        if len(candidate) <= cfg.max_chars:
            current = candidate
            continue
        if current:
            packed.append(current)
        current = piece
    if current:
        packed.append(current)

    # Fold a runt tail into its predecessor rather than leaving it to embed alone.
    if len(packed) > 1 and len(packed[-1]) < cfg.min_chars:
        tail = packed.pop()
        packed[-1] = f"{packed[-1]} {tail}".strip()

    if cfg.overlap_chars <= 0 or len(packed) < 2:
        return packed

    with_overlap = [packed[0]]
    # `packed[:-1]` and `packed[1:]` are deliberately paired: each chunk after the
    # first takes the tail of the one before it. Zipping `packed` against
    # `packed[1:]` would be an off-by-one that `strict=True` rejects outright —
    # which is exactly what it is for.
    for previous, chunk in zip(packed[:-1], packed[1:], strict=True):
        tail = previous[-cfg.overlap_chars :]
        # Start the overlap at a word boundary, so a chunk does not open with a
        # severed word that embeds to nothing meaningful.
        space = tail.find(" ")
        if space != -1:
            tail = tail[space + 1 :]
        with_overlap.append(f"{tail} {chunk}".strip() if tail else chunk)
    return with_overlap
