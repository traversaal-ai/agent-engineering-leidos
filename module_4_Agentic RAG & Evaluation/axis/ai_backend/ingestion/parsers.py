"""The shared multi-format parser — the upstream of ingestion.

Its one job is answering "what text is in this file, and where did each piece come
from" — nothing else. It stays free of any chunking assumption because the two
concerns fail differently and are read differently: a parse failure is a *file* problem
a student can see in the Parse card's unreadable-page count, and a chunking choice is a
retrieval-quality dial they can turn (System Design Section 8).

**`source_location` is the reason this module matters.** It is the string a
student reads in a citation and uses to go and check the claim. `"p. 4"` and
`"Sheet1!B2:F19"` let them find it; a chunk index would not. Getting these right
is what makes PRD Section 6's citation criterion meaningful rather than
technically satisfied.

Images are captioned to text through a `VisionProvider` (Section 10's "caption
images, embed as text"). That is a real LLM call, which is why `parse()` is async
and why an image-heavy deck costs money to ingest.
"""

from __future__ import annotations

import io
import logging
from typing import NamedTuple

from pydantic import BaseModel

from ai_backend.contracts.models import Modality
from ai_backend.contracts.providers import VisionProvider
from ai_backend.errors import IngestionError

logger = logging.getLogger("axis.ingestion")

SUPPORTED_SUFFIXES = frozenset(
    {".pdf", ".pptx", ".docx", ".xlsx", ".png", ".jpg", ".jpeg", ".md", ".txt"}
)

# `.docx`, `.md`, and `.txt` are beyond the formats PRD Section 6 names, and are
# supported deliberately. Word documents are the format an instructor is most
# likely to actually have; excluding them while accepting PowerPoint would be an
# arbitrary gap. The criterion says files "in a supported format" are accepted, so
# widening the set does not weaken it — and plain text is what makes the golden
# evaluation fixtures reviewable in a diff. A .pdf fixture is opaque: nobody can
# see what the test document says, so nobody can tell whether a failing retrieval
# test is a bug or a bad fixture.

_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

# An XLSX row is joined into one line of text. Tabs rather than commas so a value
# that itself contains a comma does not read as two columns to the LLM.
_CELL_SEPARATOR = "\t"


class ParsedBlock(BaseModel):
    """One addressable piece of a document, before any chunking.

    A block is whatever the format makes naturally addressable — a PDF page, a
    slide, a spreadsheet sheet, one image. Chunking happens downstream and may
    split or merge these; the `source_location` survives that so a citation can
    still point somewhere a human can look.
    """

    text: str
    modality: Modality = Modality.TEXT
    source_location: str = ""


class ParseResult(NamedTuple):
    """The blocks, and the addressable pieces that held no text.

    `unreadable` exists because a document is not all-or-nothing. A twenty-page scan
    with a typed cover sheet parsed "successfully" and indexed **one** page: the
    all-or-nothing guard below only fires when *nothing* is readable, so nineteen pages
    were dropped in silence, the document was marked ready, and every answer it could
    not support looked like a retrieval bug rather than a missing text layer.

    Counted rather than raised, because refusing the whole file would throw away the
    page that *is* readable — but it has to be said out loud, and by the layer that
    knows. It reaches the parse step's attributes, the document list, and the flash
    after an upload.
    """

    blocks: list[ParsedBlock]
    unreadable: list[str]


async def parse(
    filename: str,
    data: bytes,
    *,
    vision: VisionProvider | None = None,
) -> ParseResult:
    """Extract addressable text blocks from an uploaded file.

    Raises `IngestionError` for an unsupported or unreadable file — the Backend
    turns that into the per-file failure reason PRD Section 6 requires, so one bad
    file among five does not fail the batch.

    Returns the blocks that carry text *and* the locations of those that did not, so
    a partial extraction can be reported instead of passing as a whole one.
    """
    suffix = _suffix(filename)
    if suffix not in SUPPORTED_SUFFIXES:
        raise IngestionError(
            f"{filename!r} has an unsupported type ({suffix or 'no extension'}).",
            detail=f"Supported: {', '.join(sorted(SUPPORTED_SUFFIXES))}.",
        )
    if not data:
        raise IngestionError(f"{filename!r} is empty.")

    match suffix:
        case ".pdf":
            blocks = _parse_pdf(filename, data)
        case ".pptx":
            blocks = _parse_pptx(filename, data)
        case ".docx":
            blocks = _parse_docx(filename, data)
        case ".xlsx":
            blocks = _parse_xlsx(filename, data)
        case ".md" | ".txt":
            blocks = _parse_text(data)
        case ".png" | ".jpg" | ".jpeg":
            blocks = await _parse_image(filename, data, suffix, vision)
        case _:  # pragma: no cover - guarded by the membership check above
            raise IngestionError(f"No parser for {suffix!r}.")

    # A file that parsed cleanly but yielded nothing readable is a failure, not an
    # empty success. Indexing it would leave a document a student can see in the
    # list but can never retrieve from, which reads as a retrieval bug.
    readable = [b for b in blocks if b.text.strip()]
    if not readable:
        raise IngestionError(
            f"No readable text was found in {filename!r}.",
            detail=(
                "A scanned PDF with no text layer needs OCR, which Axis does not "
                "do — try exporting a text-based version."
            ),
        )
    return ParseResult(
        blocks=readable,
        unreadable=[b.source_location or "unknown location" for b in blocks if not b.text.strip()],
    )


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _parse_pdf(filename: str, data: bytes) -> list[ParsedBlock]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        # An encrypted PDF reports pages but extracts nothing, so it would
        # otherwise surface as the confusing "no readable text" above.
        if reader.is_encrypted:
            raise IngestionError(
                f"{filename!r} is password-protected.",
                detail="Remove the password and upload it again.",
            )
        pages = reader.pages
    except IngestionError:
        raise
    except (PdfReadError, OSError, ValueError) as exc:
        raise IngestionError(
            f"{filename!r} could not be read as a PDF.", detail=str(exc)
        ) from exc

    blocks: list[ParsedBlock] = []
    for number, page in enumerate(pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - one bad page must not lose the rest
            logger.warning("Skipped page %d of %s: %s", number, filename, exc)
            continue
        blocks.append(
            # "p. 4" — what a student would say out loud, not "page_index=3".
            ParsedBlock(text=text, modality=Modality.TEXT, source_location=f"p. {number}")
        )
    return blocks


# ---------------------------------------------------------------------------
# PPTX
# ---------------------------------------------------------------------------


def _parse_pptx(filename: str, data: bytes) -> list[ParsedBlock]:
    from pptx import Presentation

    try:
        deck = Presentation(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - python-pptx raises broadly
        raise IngestionError(
            f"{filename!r} could not be read as a PowerPoint file.", detail=str(exc)
        ) from exc

    blocks: list[ParsedBlock] = []
    for number, slide in enumerate(deck.slides, start=1):
        parts: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                parts.append(shape.text_frame.text.strip())
            # A table on a slide is tabular data, so it is flattened the same way
            # a spreadsheet is rather than losing its row structure.
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    if any(cells):
                        parts.append(_CELL_SEPARATOR.join(cells))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            parts.append(f"Speaker notes: {slide.notes_slide.notes_text_frame.text.strip()}")

        blocks.append(
            ParsedBlock(
                text="\n".join(parts),
                modality=Modality.TEXT,
                source_location=f"slide {number}",
            )
        )
    return blocks


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def _parse_docx(filename: str, data: bytes) -> list[ParsedBlock]:
    """One block per heading section, plus a block per table.

    **Why headings and not page numbers.** A `.docx` has no pages until something
    lays it out — pagination depends on the renderer, the fonts, and the paper
    size, and `python-docx` cannot see it. So "p. 4" is not available, and
    inventing one would produce a citation that sends a student to the wrong place.
    A heading is the document's own idea of where a section begins, which is both
    honest and more useful to read: "Parental leave" beats "p. 4" in a citation.

    Tables become their own blocks with `Modality.TABLE`, so the chunker keeps them
    whole — splitting a table separates a value from the header that gives it
    meaning.
    """
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - python-docx raises broadly
        # One handler, because the failure modes are not usefully distinguishable
        # from here: a legacy `.doc` renamed to `.docx` surfaces as `BadZipFile`
        # (it is not a zip at all), a truncated upload as `PackageNotFoundError`,
        # and a corrupt archive as either. What the reader needs is the same in
        # every case — the most likely cause and what to do — so the hint is given
        # unconditionally and the library's own reason appended for the log.
        raise IngestionError(
            f"{filename!r} could not be read as a Word document.",
            detail=(
                "Only .docx is supported. If this was saved as the older binary "
                ".doc format, re-save it as .docx — they are entirely different "
                f"formats despite the similar name. ({exc})"
            ),
        ) from exc

    blocks: list[ParsedBlock] = []
    heading = ""
    body: list[str] = []

    def flush() -> None:
        text = "\n".join(body).strip()
        if not text:
            return
        # The heading is prepended so it travels into the embedding: a section
        # stating "16 weeks" is only retrievable for "parental leave" if both
        # appear in the same chunk.
        blocks.append(
            ParsedBlock(
                text=f"{heading}\n{text}" if heading else text,
                modality=Modality.TEXT,
                source_location=heading or "document",
            )
        )

    # Walked as XML rather than via `document.paragraphs` and `document.tables`,
    # because those are two separate collections and reading them in turn would
    # move every table to the end of the document — detaching it from the section
    # that explains it, and giving it a citation pointing at the wrong heading.
    for child in document.element.body.iterchildren():
        tag = child.tag.split("}")[-1]

        if tag == "p":
            paragraph = Paragraph(child, document)
            content = paragraph.text.strip()
            if not content:
                continue
            style = (paragraph.style.name or "") if paragraph.style else ""
            if style.startswith("Heading") or style == "Title":
                flush()
                heading = content
                body = []
            else:
                body.append(content)

        elif tag == "tbl":
            # Flush the section's prose first, or the table would be emitted ahead
            # of the paragraphs that introduce it — document order preserved
            # between sections but inverted within one, which is the confusing
            # half-correct version.
            flush()
            body = []

            rows = [
                _CELL_SEPARATOR.join(cell.text.strip() for cell in row.cells)
                for row in Table(child, document).rows
            ]
            rows = [r for r in rows if r.strip(_CELL_SEPARATOR).strip()]
            if rows:
                blocks.append(
                    ParsedBlock(
                        text="\n".join(rows),
                        modality=Modality.TABLE,
                        source_location=(
                            f"table under {heading}" if heading else "table"
                        ),
                    )
                )

    flush()
    return blocks


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------


def _parse_xlsx(filename: str, data: bytes) -> list[ParsedBlock]:
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter

    try:
        # read_only keeps a large sheet from being loaded whole; data_only reads
        # cached formula *results*, because "=SUM(B2:B40)" is not an answer to
        # anything a student would ask.
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - openpyxl raises broadly
        raise IngestionError(
            f"{filename!r} could not be read as an Excel file.", detail=str(exc)
        ) from exc

    blocks: list[ParsedBlock] = []
    try:
        for sheet in workbook.worksheets:
            lines: list[str] = []
            max_row = 0
            max_col = 0
            for row_index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                values = ["" if v is None else str(v).strip() for v in row]
                if not any(values):
                    continue
                # Trailing empties are noise from a sheet's nominal dimensions.
                while values and not values[-1]:
                    values.pop()
                lines.append(_CELL_SEPARATOR.join(values))
                max_row = row_index
                max_col = max(max_col, len(values))

            if not lines:
                continue

            # "Sheet1!A1:F19" — an address a student can type into Excel and land
            # on the exact data the answer came from.
            span = f"A1:{get_column_letter(max(max_col, 1))}{max_row}"
            blocks.append(
                ParsedBlock(
                    text=f"Sheet {sheet.title}\n" + "\n".join(lines),
                    modality=Modality.TABLE,
                    source_location=f"{sheet.title}!{span}",
                )
            )
    finally:
        workbook.close()
    return blocks


# ---------------------------------------------------------------------------
# Plain text and Markdown
# ---------------------------------------------------------------------------


def _parse_text(data: bytes) -> list[ParsedBlock]:
    """One block per Markdown section, or the whole file when it has no headings.

    Splitting on headings rather than handing over one huge block gives citations
    something meaningful to name — "Parental leave" beats "part 3 of 9" — and it
    aligns chunk boundaries with the document's own structure, which is what
    recursive chunking is trying to approximate anyway.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise IngestionError(
                "The file is not valid UTF-8 text.", detail=str(exc)
            ) from exc

    blocks: list[ParsedBlock] = []
    heading = ""
    body: list[str] = []

    def flush() -> None:
        content = "\n".join(body).strip()
        if content:
            # The heading is prepended to the body so it travels into the
            # embedding: a section that says "16 weeks" is only retrievable for
            # "parental leave" if those words are in the same chunk.
            blocks.append(
                ParsedBlock(
                    text=f"{heading}\n{content}" if heading else content,
                    modality=Modality.TEXT,
                    source_location=heading or "document",
                )
            )

    for line in text.splitlines():
        if line.startswith("#"):
            flush()
            heading = line.lstrip("#").strip()
            body = []
        else:
            body.append(line)
    flush()

    return blocks or [
        ParsedBlock(text=text, modality=Modality.TEXT, source_location="document")
    ]


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


async def _parse_image(
    filename: str, data: bytes, suffix: str, vision: VisionProvider | None
) -> list[ParsedBlock]:
    if vision is None:
        raise IngestionError(
            f"{filename!r} is an image, and no vision provider is configured to "
            f"caption it.",
            detail=(
                "Set AXIS_VISION__PROVIDER=openai or =anthropic, or upload PDF, "
                "PPTX, and XLSX documents instead."
            ),
        )

    # Decode before spending money on a caption: a truncated or mislabelled image
    # should fail locally, not after a paid round trip.
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except Exception as exc:  # noqa: BLE001 - Pillow raises broadly
        raise IngestionError(
            f"{filename!r} could not be read as an image.", detail=str(exc)
        ) from exc

    caption = await vision.caption_image(data, mime_type=_IMAGE_MIME[suffix])
    if not caption.text.strip():
        raise IngestionError(
            f"The vision provider returned no description for {filename!r}."
        )

    return [
        ParsedBlock(
            text=caption.text,
            modality=Modality.IMAGE,
            # Named as a caption so a student reading the trace understands the
            # retrieved text was generated from the image, not read off it.
            source_location="image caption",
        )
    ]


def _suffix(filename: str) -> str:
    _, _, ext = (filename or "").rpartition(".")
    return f".{ext.lower()}" if ext else ""
