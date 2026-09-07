"""PRD Section 5 — student must-have:

    "I want to upload up to 5 documents so that I can test retrieval on my own
    material."

PRD Section 6 acceptance criteria:

    (a) Given a valid session, when a student uploads between 1 and 5 files in a
        supported format (PDF, PPTX, XLSX, PNG/JPG), then all files are accepted,
        parsed, and confirmed with a per-file status (success/failed with reason).

    (b) Given a 6th file is uploaded to a session already holding 5, when the
        upload is submitted, then it is rejected with a clear "limit reached"
        message and no partial state change.

The two clauses land at different milestones, so they are marked separately
rather than deferring the whole story. Clause (b) is pure Backend validation —
counting, limits, and refusing atomically — which System Design Section 6.1
places in this layer regardless of how parsing works, so it is green at Milestone
-1. Clause (a) needs the parser, which is Milestone 0.

Marking them together would hide a criterion that already holds, and would leave
the limit rule untested for a whole milestone.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.story("upload up to 5 documents")

# Real, parseable documents. An earlier version of this module used a byte string
# that merely began with "%PDF-1.4"; that was adequate while ingestion was a no-op
# and became a lie the moment a real parser existed.
from tests.docfixtures import make_pdf  # noqa: E402

_HANDBOOK = (
    "Employee handbook. Parental leave is 16 weeks of paid time off. "
    "Remote work is permitted for up to three days each week."
)
_PDF = make_pdf(_HANDBOOK)


def _file(name: str, content: bytes = _PDF, mime: str = "application/pdf"):
    return ("files", (name, content, mime))


# ---------------------------------------------------------------------------
# Clause (b) — the limit. Green at Milestone -1.
# ---------------------------------------------------------------------------


@pytest.mark.milestone(-1)
async def test_sixth_file_is_rejected_with_limit_reached(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    session_id = str(session["session_id"])
    url = f"/api/v1/sessions/{session_id}/documents"

    first = await client.post(
        url, files=[_file(f"doc{i}.pdf") for i in range(5)], headers=auth
    )
    assert first.status_code == 200, first.text

    sixth = await client.post(url, files=[_file("doc6.pdf")], headers=auth)

    assert sixth.status_code == 413, sixth.text
    body = sixth.json()
    assert body["code"] == "upload_limit_reached", body
    assert "limit reached" in body["message"].lower(), body["message"]


async def test_a_full_session_says_so_instead_of_offering_an_upload(
    client: httpx.AsyncClient,
) -> None:
    """The limit is stated on the page, not discovered by hitting it.

    The Backend refuses the sixth file correctly (above), and that was the *only* way
    to find out: the file picker stayed live, would open, accept a 25 MB selection and
    throw it away. A control that cannot act should not look like it can.

    Disabling it is safe here in a way it is not in general — see
    `test_the_upload_button_is_enabled_in_the_markup`. `full` is server-rendered from
    what the session holds, so it can only change on a page load, and there is no state
    for a scripts-disabled browser to get stuck in.
    """
    limit = 5
    empty = (await client.get("/")).text
    assert "disabled" not in _upload_form(empty), "an empty session refuses uploads"

    await client.post(
        "/upload",
        files=[_file(f"doc{i}.pdf") for i in range(limit)],
        follow_redirects=True,
    )

    page = (await client.get("/")).text
    form = _upload_form(page)
    assert "disabled" in form, "the file picker is still live at the file limit"
    assert f"Maximum of {limit} files reached" in form, (
        "nothing on the page says why the upload is closed"
    )


async def test_the_accepted_formats_and_size_limit_are_on_the_page(
    client: httpx.AsyncClient,
) -> None:
    """`accept=` filters the file dialog and tells the page's reader nothing.

    So "why won't it take my .csv?" had no answer anywhere in the UI, and the size
    limit was only discoverable by exceeding it.
    """
    form = _upload_form((await client.get("/")).text)

    for extension in ("pdf", "docx", "xlsx", "pptx", "png", "md", "txt"):
        assert extension in form, f"{extension} is not listed as an accepted format"
    assert "25 MB each" in form, "the per-file size limit is not stated"


def _upload_form(page: str) -> str:
    """The upload form as rendered, so assertions cannot match the rest of the page."""
    return page.split('id="upload-form"', 1)[1].split("</form>", 1)[0]


@pytest.mark.milestone(-1)
async def test_rejected_upload_leaves_no_partial_state(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str], backend_app
) -> None:
    """"no partial state change" — the clause that constrains the implementation.

    Validating and storing file-by-file would leave the first few rows written
    when the batch is refused. That is a plausible implementation which passes a
    naive reading of the criterion and fails this test, which is the point of
    writing the test from the criterion rather than from the code.
    """
    session_id = str(session["session_id"])
    url = f"/api/v1/sessions/{session_id}/documents"

    await client.post(url, files=[_file(f"doc{i}.pdf") for i in range(4)], headers=auth)
    before = backend_app.state.documents.count_for_session(session_id)
    assert before == 4

    # Four held plus three submitted exceeds five: the whole batch must be refused.
    response = await client.post(
        url, files=[_file(f"extra{i}.pdf") for i in range(3)], headers=auth
    )
    assert response.status_code == 413, response.text

    after = backend_app.state.documents.count_for_session(session_id)
    assert after == before, "a refused batch must not have stored any of its files"


@pytest.mark.milestone(-1)
async def test_unsupported_file_type_is_refused(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """Format validation, per the supported list in the criterion."""
    response = await client.post(
        f"/api/v1/sessions/{str(session['session_id'])}/documents",
        files=[("files", ("notes.exe", b"MZ\x90\x00", "application/octet-stream"))],
        headers=auth,
    )

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "invalid_request"


@pytest.mark.milestone(-1)
async def test_upload_requires_a_session_token(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/sessions/does-not-exist/documents", files=[_file("doc.pdf")]
    )

    assert response.status_code == 401, response.text


# ---------------------------------------------------------------------------
# Clause (a) — parsing and per-file confirmation. Milestone 0.
# ---------------------------------------------------------------------------


@pytest.mark.milestone(0)
async def test_uploaded_files_are_parsed_and_confirmed_individually(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """All five accepted, parsed, and each confirmed with its own status."""
    response = await client.post(
        f"/api/v1/sessions/{str(session['session_id'])}/documents",
        files=[_file(f"doc{i}.pdf") for i in range(5)],
        headers=auth,
    )

    assert response.status_code == 200, response.text
    body = response.json()

    assert len(body["documents"]) == 5
    assert body["accepted"] == 5
    for entry in body["documents"]:
        assert entry["status"] == "ready", entry
        assert entry["document_id"]

    # "parsed" is the part that distinguishes this from clause (b): the content
    # must be indexed, not merely recorded. A document row with no chunks behind
    # it would satisfy a weaker reading and leave retrieval with nothing to find.
    chunks = await client.get(
        f"/api/v1/sessions/{str(session['session_id'])}/documents", headers=auth
    )
    assert chunks.status_code == 200
    assert any(d.get("chunk_count", 0) > 0 for d in chunks.json())


@pytest.mark.milestone(0)
async def test_one_unreadable_file_does_not_fail_the_others(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """"per-file status (success/failed with reason)".

    A corrupt PDF among four good ones must be reported as failed *with a reason*
    while the other four succeed. All-or-nothing on parse failure would be the
    obvious implementation and is not what the criterion asks for.
    """
    response = await client.post(
        f"/api/v1/sessions/{str(session['session_id'])}/documents",
        files=[
            _file("good1.pdf"),
            _file("good2.pdf"),
            _file("corrupt.pdf", b"not a pdf at all"),
            _file("good3.pdf"),
        ],
        headers=auth,
    )

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["accepted"] == 3
    assert body["rejected"] == 1
    failed = [d for d in body["documents"] if d["status"] == "failed"]
    assert len(failed) == 1
    assert failed[0]["filename"] == "corrupt.pdf"
    assert failed[0]["error"], "a failed file must carry a reason"


async def test_a_scanned_pdf_is_told_that_axis_does_no_ocr(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """The remedy, not only the diagnosis.

    "No readable text was found in 'scan.pdf'" tells a student nothing they can do. The
    sentence that does — that Axis performs no OCR and a text-based export will work —
    was written as `AxisError.detail`, travelled as far as the error payload, and was
    dropped by the one route a student's upload actually goes through.
    """
    response = await client.post(
        f"/api/v1/sessions/{str(session['session_id'])}/documents",
        # A valid PDF whose only page draws no text — a scan, as far as any extractor
        # is concerned.
        files=[_file("scan.pdf", make_pdf(""))],
        headers=auth,
    )

    assert response.status_code == 200, response.text
    failed = [d for d in response.json()["documents"] if d["status"] == "failed"]
    assert len(failed) == 1, response.json()
    assert "ocr" in (failed[0].get("detail") or "").lower(), (
        "the student is told the file is unreadable and not that OCR is what is missing"
    )


async def test_a_partly_scanned_pdf_reports_what_it_dropped(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """Indexed, and not in full — said out loud, at every layer that can say it.

    Three pages, one with a text layer. It indexes, which is right: the readable page
    is useful. But "1 indexed" is the whole story a student used to get, and it is
    technically true and completely misleading — the document answers a twentieth of
    what they think it does.
    """
    response = await client.post(
        f"/api/v1/sessions/{str(session['session_id'])}/documents",
        files=[_file("mixed.pdf", make_pdf("Cover sheet: employee handbook.", "", ""))],
        headers=auth,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["accepted"] == 1, body
    document = body["documents"][0]
    assert document["status"] == "ready"

    note = document.get("note") or ""
    assert "2 of 3 pages" in note, note
    assert "ocr" in note.lower(), "the note does not say what would have read them"


async def test_the_parse_step_records_the_pages_it_could_not_read(
    client: httpx.AsyncClient, session: dict, auth: dict[str, str]
) -> None:
    """The durable half.

    The upload note is one banner and then gone. The trace is the authenticity record
    and the canvas draws it, so a partial extraction has to be visible there too —
    otherwise the only lasting evidence is a chunk count nobody has a baseline for.
    """
    session_id = str(session["session_id"])
    await client.post(
        f"/api/v1/sessions/{session_id}/documents",
        files=[_file("mixed.pdf", make_pdf("Cover sheet.", "", ""))],
        headers=auth,
    )

    steps = (
        await client.get(f"/api/v1/sessions/{session_id}/trace/steps", headers=auth)
    ).json()
    parse_steps = [s for s in steps if s["step_type"] == "parse"]
    assert parse_steps, steps

    attributes = parse_steps[-1]["attributes"]
    assert attributes["unreadable_blocks"] == 2, attributes
    assert attributes["unreadable_locations"] == ["p. 2", "p. 3"], attributes
