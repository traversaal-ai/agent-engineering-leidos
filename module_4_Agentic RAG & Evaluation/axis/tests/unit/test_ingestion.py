"""Parsing, chunking, and upload safety.

The parser tests care most about `source_location`, because that string is what a
student reads in a citation and follows to check a claim. "p. 4" is useful;
"chunk 7" is not, and a test that only checked text extraction would let the
useful version silently become the useless one.
"""

from __future__ import annotations

import pytest

from ai_backend.contracts.models import Modality
from ai_backend.errors import IngestionError
from ai_backend.ingestion.chunker import ChunkingConfig, chunk_blocks
from ai_backend.ingestion.parsers import ParsedBlock, parse
from ai_backend.ingestion.safety import assert_safe_archive
from ai_backend.observability import trace_context
from ai_backend.providers.fake import FakeVisionProvider
from tests.docfixtures import (
    make_docx,
    make_pdf,
    make_png,
    make_pptx,
    make_xlsx,
    make_zip_bomb,
)

# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


async def test_pdf_pages_are_addressable_by_page_number() -> None:
    data = make_pdf("First page about leave.", "Second page about expenses.")

    blocks, _ = await parse("handbook.pdf", data)

    assert [b.source_location for b in blocks] == ["p. 1", "p. 2"]
    assert "leave" in blocks[0].text
    assert "expenses" in blocks[1].text


async def test_pptx_slides_are_addressable_by_slide_number() -> None:
    data = make_pptx(("Leave policy", "16 weeks paid"), ("Remote", "Three days"))

    blocks, _ = await parse("deck.pptx", data)

    assert [b.source_location for b in blocks] == ["slide 1", "slide 2"]
    assert "16 weeks" in blocks[0].text


async def test_docx_sections_are_addressable_by_heading() -> None:
    """A `.docx` has no page numbers to cite.

    Pagination happens at render time and `python-docx` cannot see it, so "p. 4"
    is unavailable — and inventing one would send a student to the wrong place.
    Headings are the document's own idea of where a section starts, and read
    better in a citation anyway.
    """
    data = make_docx(
        ("Parental leave", "Employees receive 16 weeks of fully paid leave."),
        ("Remote work", "Up to three days each week."),
    )

    blocks, _ = await parse("handbook.docx", data)

    assert [b.source_location for b in blocks] == ["Parental leave", "Remote work"]
    assert "16 weeks" in blocks[0].text
    # The heading travels into the text, so the section is retrievable by its own
    # title and not only by its body.
    assert blocks[0].text.startswith("Parental leave")


async def test_a_docx_table_stays_with_its_section_and_in_order() -> None:
    """Two things at once, both of which were wrong at first.

    `python-docx` exposes paragraphs and tables as *separate* collections, so
    reading them in turn moves every table to the end of the document — detached
    from the section that explains it and citing the wrong heading. And flushing
    the section's prose only on the next heading emitted the table *before* the
    paragraphs introducing it. Walking the body XML fixes the first; flushing
    before a table fixes the second.
    """
    data = make_docx(
        ("Parental leave", "Employees receive 16 weeks of paid leave."),
        ("Rates", "Daily rates by band are below."),
        table=[["Band", "Rate"], ["Senior", "950"]],
    )

    blocks, _ = await parse("handbook.docx", data)

    assert [b.source_location for b in blocks] == [
        "Parental leave",
        "Rates",
        "table under Rates",
    ]
    table = blocks[-1]
    assert table.modality is Modality.TABLE
    # Rows survive as rows: a value split from its header means nothing.
    assert "Band\tRate" in table.text
    assert "950" in table.text


async def test_a_docx_with_no_headings_still_parses() -> None:
    """Plenty of real documents have no heading styles at all."""
    import io as _io

    from docx import Document as _Docx

    document = _Docx()
    document.add_paragraph("Parental leave is 16 weeks of paid time off.")
    buffer = _io.BytesIO()
    document.save(buffer)

    blocks, _ = await parse("plain.docx", buffer.getvalue())

    assert len(blocks) == 1
    assert blocks[0].source_location == "document"
    assert "16 weeks" in blocks[0].text


async def test_a_corrupt_docx_is_refused_and_names_the_doc_format() -> None:
    """The most likely cause is someone uploading a legacy binary `.doc`.

    Saying so beats a generic parse failure: `.doc` and `.docx` are entirely
    different formats, and "re-save it as .docx" is an action the reader can take.
    """
    with pytest.raises(IngestionError) as excinfo:
        await parse("broken.docx", b"this is not a word document")

    assert "broken.docx" in excinfo.value.message
    assert ".docx" in (excinfo.value.detail or "")


async def test_a_legacy_doc_is_refused_as_unsupported() -> None:
    with pytest.raises(IngestionError) as excinfo:
        await parse("old.doc", b"\xd0\xcf\x11\xe0 legacy binary word")

    assert "unsupported type (.doc)" in excinfo.value.message


def test_a_docx_is_covered_by_the_zip_bomb_guard() -> None:
    """`.docx` is a zip archive too, so it needs the same ceiling as PPTX/XLSX."""
    from ai_backend.ingestion.safety import ZIP_BACKED_SUFFIXES

    assert ".docx" in ZIP_BACKED_SUFFIXES

    with pytest.raises(IngestionError):
        assert_safe_archive(
            "bomb.docx", make_zip_bomb(), max_uncompressed_bytes=50 * 1024 * 1024
        )


async def test_xlsx_sheets_carry_a_cell_range() -> None:
    """"Sheet1!A1:C4" is an address a student can type into Excel."""
    data = make_xlsx({"Rates": [["Band", "Rate"], ["Senior", 950]]})

    blocks, _ = await parse("rates.xlsx", data)

    assert len(blocks) == 1
    assert blocks[0].source_location == "Rates!A1:B2"
    assert blocks[0].modality is Modality.TABLE
    # Rows survive as rows: a value separated from its header means nothing.
    assert "Band" in blocks[0].text
    assert "950" in blocks[0].text


async def test_markdown_sections_become_separate_blocks() -> None:
    data = b"# Leave\n16 weeks paid.\n\n# Remote\nThree days a week."

    blocks, _ = await parse("handbook.md", data)

    assert [b.source_location for b in blocks] == ["Leave", "Remote"]
    # The heading is carried into the text, so the section is retrievable by its
    # own title and not only by its body.
    assert blocks[0].text.startswith("Leave")


async def test_an_image_is_captioned_through_the_vision_provider() -> None:
    vision = FakeVisionProvider()

    # Captioning is a traced provider call, so it needs a session to attribute the
    # step to — the cost of captioning an image-heavy deck belongs in the trace.
    with trace_context(session_id="s1", trace_id="t1"):
        blocks, _ = await parse("chart.png", make_png(), vision=vision)

    assert vision.call_count == 1
    assert blocks[0].modality is Modality.IMAGE
    assert blocks[0].source_location == "image caption"
    assert blocks[0].text


async def test_an_image_without_a_vision_provider_explains_itself() -> None:
    """A configuration gap, reported as one — not a crash and not a silent skip."""
    with pytest.raises(IngestionError) as excinfo:
        await parse("chart.png", make_png(), vision=None)

    assert "AXIS_VISION__PROVIDER" in (excinfo.value.detail or "")


async def test_a_corrupt_pdf_is_refused_with_a_reason() -> None:
    with pytest.raises(IngestionError) as excinfo:
        await parse("broken.pdf", b"this is definitely not a pdf")

    assert "broken.pdf" in excinfo.value.message


async def test_an_unsupported_type_lists_what_is_supported() -> None:
    with pytest.raises(IngestionError) as excinfo:
        await parse("virus.exe", b"MZ\x90\x00")

    assert ".pdf" in (excinfo.value.detail or "")


async def test_an_empty_file_is_refused() -> None:
    with pytest.raises(IngestionError):
        await parse("empty.pdf", b"")


async def test_a_pdf_with_no_text_layer_is_a_failure_not_an_empty_success() -> None:
    """A scanned PDF needs OCR, which Axis does not do.

    Indexing it as an empty document would leave a file a student can see in their
    list but can never retrieve from — which reads as a retrieval bug rather than
    an unsupported document.
    """
    # A valid PDF whose page draws no text.
    with pytest.raises(IngestionError) as excinfo:
        await parse("scan.pdf", make_pdf(""))

    assert "no readable text" in excinfo.value.message.lower()
    assert "ocr" in (excinfo.value.detail or "").lower()


async def test_a_partly_scanned_pdf_reports_the_pages_it_could_not_read() -> None:
    """The bug this was written for: a partial extraction passing as a whole one.

    A scan with a typed cover sheet is the common shape, and the all-or-nothing guard
    above only fires when *nothing* is readable. So a twenty-page document indexed its
    one text page, was marked ready, and said nothing — and every question it could not
    answer read as a retrieval bug rather than as nineteen pages of picture.

    Refusing the file would be wrong: the readable page is genuinely useful. Counting
    what was dropped is what makes the result honest.
    """
    # Page 1 has text; pages 2 and 3 draw nothing, exactly as a scanned page does.
    blocks, unreadable = await parse("mixed.pdf", make_pdf("Cover sheet.", "", ""))

    assert [b.source_location for b in blocks] == ["p. 1"]
    assert unreadable == ["p. 2", "p. 3"], (
        "the pages with no text layer were dropped without being counted"
    )


async def test_a_fully_readable_document_reports_nothing_unreadable() -> None:
    """The other half, so "0 skipped" is a measurement rather than a default.

    Without this, a bug that stopped counting would look identical to a clean parse.
    """
    blocks, unreadable = await parse("handbook.pdf", make_pdf("One.", "Two."))

    assert len(blocks) == 2
    assert unreadable == []


# ---------------------------------------------------------------------------
# Zip-bomb protection (System Design Section 6.5, priority 3)
# ---------------------------------------------------------------------------


def test_a_zip_bomb_is_refused_without_being_decompressed() -> None:
    """The archive directory is read; nothing is expanded.

    A small file that claims a ~1 GB expansion must be refused. Axis runs as one
    process during a live demo, so an OOM here is not a failed upload — it is a
    dead classroom.
    """
    bomb = make_zip_bomb()

    # The file itself is tiny; the danger is entirely in what it claims to hold.
    assert len(bomb) < 2 * 1024 * 1024

    with pytest.raises(IngestionError) as excinfo:
        assert_safe_archive("bomb.xlsx", bomb, max_uncompressed_bytes=50 * 1024 * 1024)

    assert "expands to more than" in excinfo.value.message


def test_a_normal_office_file_passes_the_archive_check() -> None:
    assert_safe_archive(
        "rates.xlsx",
        make_xlsx({"Rates": [["a", 1]]}),
        max_uncompressed_bytes=50 * 1024 * 1024,
    )


def test_a_non_archive_format_skips_the_check() -> None:
    """A PDF is not a zip, so there is nothing to inspect."""
    assert_safe_archive("doc.pdf", make_pdf("hello"), max_uncompressed_bytes=1)


def test_a_corrupt_archive_is_refused() -> None:
    with pytest.raises(IngestionError):
        assert_safe_archive(
            "broken.xlsx", b"not a zip", max_uncompressed_bytes=50 * 1024 * 1024
        )


# ---------------------------------------------------------------------------
# Chunker
# ---------------------------------------------------------------------------


def _block(text: str, **kwargs) -> ParsedBlock:
    return ParsedBlock(text=text, source_location=kwargs.pop("loc", "p. 1"), **kwargs)


def test_short_text_stays_one_chunk() -> None:
    chunks = chunk_blocks([_block("A short paragraph.")], document_id="d1")

    assert len(chunks) == 1
    assert chunks[0].source_location == "p. 1"


def test_long_text_splits_at_sentence_boundaries() -> None:
    """Recursive splitting, not fixed-size windows.

    A chunk that begins mid-sentence embeds to something subtly different from the
    text it came from, which is the whole reason Section 10 chose recursive over
    fixed-size.
    """
    sentences = [f"Sentence number {i} about company policy." for i in range(60)]
    config = ChunkingConfig(max_chars=300, overlap_chars=0, min_chars=50)

    chunks = chunk_blocks([_block(" ".join(sentences))], document_id="d1", config=config)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.content) <= 400  # budget plus the tail of a sentence
        # No chunk begins mid-word.
        assert not chunk.content.startswith(" ")


def test_a_split_block_reports_which_part_it_is() -> None:
    """So a citation stays precise instead of naming a five-page span."""
    config = ChunkingConfig(max_chars=120, overlap_chars=0, min_chars=20)
    text = " ".join(f"Policy statement {i} follows here." for i in range(30))

    chunks = chunk_blocks([_block(text, loc="p. 7")], document_id="d1", config=config)

    assert len(chunks) > 1
    assert all(c.source_location.startswith("p. 7 (") for c in chunks)
    assert chunks[0].source_location == f"p. 7 (1/{len(chunks)})"


def test_overlap_carries_context_across_a_boundary() -> None:
    """A fact straddling a boundary would otherwise be unretrievable.

    The chunk with the question's keywords would lack the answer, and the chunk
    with the answer would lack the keywords.
    """
    text = " ".join(f"word{i}" for i in range(200))
    config = ChunkingConfig(max_chars=200, overlap_chars=60, min_chars=20)

    chunks = chunk_blocks([_block(text)], document_id="d1", config=config)

    assert len(chunks) > 1
    # The second chunk repeats the tail of the first.
    tail_words = set(chunks[0].content.split()[-6:])
    assert tail_words & set(chunks[1].content.split())


def test_overlap_starts_at_a_word_boundary() -> None:
    text = " ".join(f"policy{i}" for i in range(120))
    config = ChunkingConfig(max_chars=180, overlap_chars=25, min_chars=20)

    chunks = chunk_blocks([_block(text)], document_id="d1", config=config)

    for chunk in chunks[1:]:
        first = chunk.content.split()[0]
        assert first.startswith("policy"), f"severed word at chunk start: {first!r}"


def test_a_table_is_kept_whole_when_it_fits() -> None:
    """Splitting a table separates a value from its header."""
    table = "Band\tRate\nJunior\t450\nSenior\t950"

    chunks = chunk_blocks(
        [_block(table, modality=Modality.TABLE)],
        document_id="d1",
        config=ChunkingConfig(max_chars=1000),
    )

    assert len(chunks) == 1
    assert chunks[0].modality is Modality.TABLE


def test_blocks_are_never_merged_across_boundaries() -> None:
    """Two pages must not share a chunk.

    A merged chunk can only carry one citation, so a student following it lands on
    the wrong page — the token saving is not worth a dishonest citation.
    """
    chunks = chunk_blocks(
        [_block("Page one text.", loc="p. 1"), _block("Page two text.", loc="p. 2")],
        document_id="d1",
        config=ChunkingConfig(max_chars=5000),
    )

    assert len(chunks) == 2
    assert {c.source_location for c in chunks} == {"p. 1", "p. 2"}


def test_a_runt_tail_is_folded_into_its_predecessor() -> None:
    """A 20-character chunk embeds to noise and pollutes retrieval."""
    text = " ".join(f"word{i}" for i in range(41))
    config = ChunkingConfig(max_chars=100, overlap_chars=0, min_chars=60)

    chunks = chunk_blocks([_block(text)], document_id="d1", config=config)

    assert all(len(c.content) >= 40 for c in chunks), [len(c.content) for c in chunks]


def test_empty_blocks_produce_no_chunks() -> None:
    assert chunk_blocks([_block("   \n  \n ")], document_id="d1") == []


def test_every_chunk_belongs_to_its_document() -> None:
    chunks = chunk_blocks([_block("Some text here.")], document_id="doc-42")

    assert all(c.document_id == "doc-42" for c in chunks)
