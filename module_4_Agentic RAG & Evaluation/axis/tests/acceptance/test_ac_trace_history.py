"""PRD Section 5 — student must-have:

    "As a student, I want to open any run this session has made — an upload, an earlier
    question, a summary — and read every step of it, so that I can compare what one
    strategy did against what the other did."

PRD Section 6, *Read any run*.

The raw trace showed the *last* run and nothing else. Every earlier one was in the store
and unreachable, so the page could answer "what did that just do?" and not "what did it
do differently last time?" — which is the comparison the platform exists to teach and the
only reason to keep a raw trace at all.

The load-bearing tests here are the two that would let the list lie: that a run's cost is
the sum of its *top-level* steps rather than of every step (a parent aggregates its
children's usage, so the naive sum doubles every LLM call), and that selecting a run
shows that run's steps and no others.
"""

from __future__ import annotations

import re

import httpx
import pytest

from ai_backend.contracts.models import Strategy
from tests.docfixtures import make_pdf

pytestmark = [
    pytest.mark.story("read any run this session has made"),
    pytest.mark.milestone(3),
]

_HANDBOOK = (
    "Parental leave. Employees are entitled to 16 weeks of fully paid parental "
    "leave following the birth or adoption of a child. Remote work. Employees may "
    "work remotely for up to three days each week."
)


def _runs(page: str) -> list[str]:
    """The trace ids the picker offers, in the order it offers them."""
    return re.findall(r'class="tracerun"\s+href="/trace\?id=([^"]+)"', page)


async def _a_session_with_history(client: httpx.AsyncClient) -> None:
    """One upload and two questions — three runs, of two different kinds."""
    await client.post(
        "/upload",
        files=[("files", ("handbook.pdf", make_pdf(_HANDBOOK), "application/pdf"))],
        follow_redirects=True,
    )
    for question in ("How long is parental leave?", "Can I work remotely?"):
        await client.post(
            "/ask", data={"question": question, "strategy": Strategy.NAIVE_RAG.value}
        )


async def test_every_run_in_the_session_is_listed(client: httpx.AsyncClient) -> None:
    """"any run this session has made" — indexing included.

    Indexing is a run like any other and belongs in the list: what a document cost to
    index is half of what the platform measures, and it was previously visible only in
    the seconds it took to happen.
    """
    await _a_session_with_history(client)
    page = (await client.get("/trace")).text

    assert len(_runs(page)) == 3, "an upload and two questions are three runs"
    assert "3 runs this session" in page
    # Each says what it was, in its own words rather than by position.
    assert "handbook.pdf" in page
    assert "How long is parental leave?" in page
    assert "Can I work remotely?" in page


async def test_the_newest_run_is_listed_first_and_opened_by_default(
    client: httpx.AsyncClient,
) -> None:
    """The run someone just watched is the one they came to read."""
    await _a_session_with_history(client)
    page = (await client.get("/trace")).text

    first = _runs(page)[0]
    assert re.search(
        rf'href="/trace\?id={first}"[^>]*aria-current="true"', page
    ), "the newest run is not the one opened"
    # And the newest is the last question asked, not the upload that preceded it.
    assert page.index("Can I work remotely?") < page.index("How long is parental leave?")


async def test_an_earlier_run_can_be_opened_in_full(client: httpx.AsyncClient) -> None:
    """The point of the whole change: the steps swap, the list does not.

    Asserted on the *step* area rather than the page, because both questions appear in
    the picker on either page — the picker is the constant and the steps are what
    selecting changes.
    """
    await _a_session_with_history(client)
    listing = (await client.get("/trace")).text
    newest, middle, oldest = _runs(listing)

    def steps(page: str) -> str:
        """Only the step cards — the picker sits after them and names every run."""
        if 'class="trace"' not in page:
            return ""
        return page.split('class="trace"', 1)[1].split('class="tracelist"', 1)[0]

    latest_steps = steps((await client.get(f"/trace?id={newest}")).text)
    assert "Can I work remotely?" in latest_steps
    assert "How long is parental leave?" not in latest_steps

    earlier_steps = steps((await client.get(f"/trace?id={middle}")).text)
    assert "How long is parental leave?" in earlier_steps
    assert "Can I work remotely?" not in earlier_steps

    # And the upload's own run, which has no question in it at all.
    indexing = (await client.get(f"/trace?id={oldest}")).text
    assert 'class="step step--' in steps(indexing)
    assert ">ingest<" in indexing or "ingest handbook.pdf" in indexing


async def test_an_unknown_run_falls_back_to_the_most_recent(
    client: httpx.AsyncClient,
) -> None:
    """A stale link must not 404, and must never 500.

    The only ways to hold an id that is not in this session are a bookmark taken before
    a reset and a link shared between sessions. In both cases the newest run is what the
    reader wants; being technically correct about the missing one helps nobody.
    """
    await _a_session_with_history(client)
    response = await client.get("/trace?id=nosuchtrace")

    assert response.status_code == 200
    newest = _runs(response.text)[0]
    assert f'href="/trace?id={newest}"' in response.text
    assert 'aria-current="true"' in response.text


async def test_a_run_reports_the_cost_of_its_top_level_steps(
    client: httpx.AsyncClient,
) -> None:
    """The figure that would be silently wrong, and doubly so.

    A parent step aggregates its children's usage — `synthesize` adds the completion's
    usage while the provider's nested `generate` step records the very same usage — so
    summing every step in a run reports twice the cost of every LLM call in it. The
    picker's number has to agree with the one the answer and the comparison table
    report for the same run, or the page teaches a student to distrust all three.
    """
    await client.post(
        "/upload",
        files=[("files", ("handbook.pdf", make_pdf(_HANDBOOK), "application/pdf"))],
        follow_redirects=True,
    )
    answered = await client.post(
        "/ask",
        data={"question": "How long is parental leave?", "strategy": "naive_rag"},
    )
    assert answered.status_code == 200

    # What the run actually cost, read from the steps the page itself displays.
    steps = (await client.get("/trace/recent")).json()["steps"]
    newest = _runs((await client.get("/trace")).text)[0]
    truth = sum(
        float(s["cost_usd"])
        for s in steps
        if s["trace_id"] == newest and not s["parent_step_id"]
    )
    assert truth > 0, "the run spent nothing, so this proves nothing"

    listed = re.search(
        r'href="/trace\?id=' + newest + r'"[\s\S]*?\$([0-9.]+)',
        (await client.get("/trace")).text,
    )
    assert listed, "the run's cost is not shown"
    assert float(listed.group(1)) == pytest.approx(truth, rel=0.01), (
        "the listed cost double-counts nested steps"
    )


async def test_the_picker_works_without_javascript(client: httpx.AsyncClient) -> None:
    """Every row is a real link to a real URL.

    Not a fallback here but the only mechanism: `axis.js` bails on any page without a
    canvas, so nothing on this page is enhanced at all. A picker built on a click
    handler would be dead and would look exactly like a working one — which is how the
    narration control on this same page came to be broken unnoticed.
    """
    await _a_session_with_history(client)
    page = (await client.get("/trace")).text

    for trace_id in _runs(page):
        response = await client.get(f"/trace?id={trace_id}")
        assert response.status_code == 200, trace_id
        assert 'class="step step--' in response.text, f"{trace_id} rendered no steps"


async def test_a_fresh_session_says_so_rather_than_showing_an_empty_list(
    client: httpx.AsyncClient,
) -> None:
    await client.get("/")
    page = (await client.get("/trace")).text

    assert "Nothing has run yet" in page
    assert _runs(page) == []
