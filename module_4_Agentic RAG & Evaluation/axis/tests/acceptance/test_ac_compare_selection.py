"""PRD Section 5 — student must-have:

    "As a student, I want to run Compare mode so that I can see latency, cost, and answer
    quality for both strategies side by side **on the same question**."

PRD Section 6, *Compare mode*.

The last four words of that story are the whole of this module. The page pinned the *last*
run of each strategy, whatever those runs had asked, because the run store kept one slot
per strategy and every run overwrote it. Ask one question under Naive RAG and a different
one under Agentic RAG and the page reported a cost ratio between them as though it had
measured what orchestration costs — it had measured two different pieces of work.

The load-bearing test here is `test_the_default_pairs_the_newest_question_both_answered`:
a selector nobody touches has to arrive at a valid comparison on its own, or the page is
misleading by default and correct only for the reader who already knew to fix it.
"""

from __future__ import annotations

import re

import httpx
import pytest

from ai_backend.contracts.models import Strategy
from tests.docfixtures import make_pdf

pytestmark = [pytest.mark.story("Compare mode"), pytest.mark.milestone(3)]

_POLICY = (
    "Parental leave. Employees are entitled to 16 weeks of fully paid parental leave. "
    "Remote work. Employees may work remotely for up to three days each week. "
    "Encryption. All laptops must use full-disk encryption with AES-256."
)

_SHARED = "How long is parental leave?"
_OTHER = "How are laptops encrypted?"


async def _indexed(client: httpx.AsyncClient) -> None:
    await client.post(
        "/upload",
        files=[("files", ("policy.pdf", make_pdf(_POLICY), "application/pdf"))],
        follow_redirects=True,
    )


async def _ask(client: httpx.AsyncClient, question: str, strategy: Strategy) -> None:
    response = await client.post(
        "/ask", data={"question": question, "strategy": strategy.value}
    )
    assert response.status_code == 200, response.text


def _options(page: str, strategy: str) -> list[str]:
    """The runs offered for one strategy, in the order the select lists them."""
    match = re.search(
        rf'<select id="pick-{strategy}"[^>]*>(.*?)</select>', page, re.S
    )
    assert match, f"no picker for {strategy!r}"
    return [
        re.sub(r"\s+", " ", body).strip()
        for body in re.findall(r"<option[^>]*>(.*?)</option>", match.group(1), re.S)
    ]


def _selected(page: str, strategy: str) -> str:
    match = re.search(
        rf'<select id="pick-{strategy}"[^>]*>(.*?)</select>', page, re.S
    )
    assert match
    chosen = re.search(r'<option value="([^"]+)"\s+selected', match.group(1))
    assert chosen, f"nothing selected for {strategy!r}"
    return chosen.group(1)


async def test_every_run_of_a_strategy_can_be_chosen(client: httpx.AsyncClient) -> None:
    """"one run of each strategy, chosen rather than assumed".

    Three questions under one strategy used to leave two of them unreachable: the store
    kept one slot per strategy and each run overwrote the last.
    """
    await _indexed(client)
    for question in (_SHARED, _OTHER, "Can I work remotely?"):
        await _ask(client, question, Strategy.NAIVE_RAG)

    options = _options((await client.get("/compare")).text, "naive_rag")

    assert len(options) == 3, options
    # Newest first, and each named by what it asked rather than by position.
    assert options[0].startswith("Can I work remotely?")
    assert options[1].startswith(_OTHER)
    assert options[2].startswith(_SHARED)


async def test_the_default_pairs_the_newest_question_both_answered(
    client: httpx.AsyncClient,
) -> None:
    """The regression that matters: a page nobody has touched must not mislead.

    Q1 under both strategies, then Q2 under one of them. "The last run of each" pairs Q2
    against Q1 and prints a cost ratio between two unrelated pieces of work — which is
    what the page did, and it did it by default, so the reader had no reason to doubt it.
    """
    await _indexed(client)
    await _ask(client, _SHARED, Strategy.NAIVE_RAG)
    await _ask(client, _SHARED, Strategy.AGENTIC_RAG)
    await _ask(client, _OTHER, Strategy.NAIVE_RAG)

    page = (await client.get("/compare")).text

    assert "These runs asked different questions" not in page
    assert f"Both runs answered &ldquo;{_SHARED}&rdquo;" in page
    # The naive column is the *older* run, because that is the one that matches.
    naive_options = _options(page, "naive_rag")
    assert naive_options[0].startswith(_OTHER), "the newest naive run is not Q2"
    assert _selected(page, "naive_rag") != _selected(page, "agentic_rag")
    assert "verdict" in page, "a valid comparison must still reach a finding"


async def test_comparing_two_questions_withholds_the_verdict(
    client: httpx.AsyncClient,
) -> None:
    """"a comparison of two different questions states that it is not a measure of
    orchestration, and withholds the verdict".

    The numbers stay — they are those two runs' real numbers. The verdict is the sentence
    that makes a causal claim, and there is no causal claim to make between two unrelated
    questions.
    """
    await _indexed(client)
    await _ask(client, _SHARED, Strategy.NAIVE_RAG)
    await _ask(client, _OTHER, Strategy.AGENTIC_RAG)

    page = (await client.get("/compare")).text

    assert "These runs asked different questions" in page
    assert "not what the orchestration costs" in page
    assert 'class="verdict"' not in page, "a causal claim about two unrelated runs"
    # And the evidence is still there: this is a warning, not a refusal.
    assert 'class="compare"' in page
    assert "sub-questions" in page


async def test_choosing_the_same_question_under_both_reaches_a_verdict(
    client: httpx.AsyncClient,
) -> None:
    """The case the whole page exists for, driven through the picker itself."""
    await _indexed(client)
    await _ask(client, _SHARED, Strategy.NAIVE_RAG)
    await _ask(client, _OTHER, Strategy.AGENTIC_RAG)
    await _ask(client, _SHARED, Strategy.AGENTIC_RAG)

    mismatched = (await client.get("/compare")).text
    naive = _selected(mismatched, "naive_rag")
    # The agentic run of the shared question is the newest, so the default already
    # matches; select it explicitly to prove the parameters are what drive the page.
    agentic = _selected(mismatched, "agentic_rag")

    page = (
        await client.get(f"/compare?naive_rag={naive}&agentic_rag={agentic}")
    ).text
    assert 'class="verdict"' in page
    assert "These runs asked different questions" not in page

    # And now deliberately mismatch it through the same mechanism.
    other = next(
        value
        for value in re.findall(
            r'<option value="([^"]+)"',
            re.search(r'<select id="pick-agentic_rag"[^>]*>(.*?)</select>', page, re.S).group(1),
        )
        if value != agentic
    )
    mixed = (await client.get(f"/compare?naive_rag={naive}&agentic_rag={other}")).text
    assert 'class="verdict"' not in mixed
    assert "These runs asked different questions" in mixed


async def test_both_answers_are_shown_for_the_chosen_runs(
    client: httpx.AsyncClient,
) -> None:
    """The verdict says "compare the two answers above". There were none.

    The sentence survived the split of the single scrolling page into three, so the page
    named the one thing its metrics cannot settle and then withheld it. The metrics say
    what each run cost; only the answers say what it bought.
    """
    await _indexed(client)
    await _ask(client, _SHARED, Strategy.NAIVE_RAG)
    await _ask(client, _SHARED, Strategy.AGENTIC_RAG)

    page = (await client.get("/compare")).text

    answers = page.split('class="answers"', 1)
    assert len(answers) == 2, "the chosen runs' answers are not on the page"
    assert answers[1].count('class="answer ') == 2, "only one answer is shown"
    assert 'data-strategy="naive_rag"' in answers[1]
    assert 'data-strategy="agentic_rag"' in answers[1]


async def test_an_unknown_run_falls_back_to_the_default(
    client: httpx.AsyncClient,
) -> None:
    """A stale link must not 404 and must never 500 — as on the trace page."""
    await _indexed(client)
    await _ask(client, _SHARED, Strategy.NAIVE_RAG)

    response = await client.get("/compare?naive_rag=nosuchrun")

    assert response.status_code == 200
    assert 'class="compare"' in response.text


async def test_choosing_runs_works_without_javascript(
    client: httpx.AsyncClient,
) -> None:
    """A `GET` form with a submit button, and field names that are strategy values.

    `axis.js` submits it on change, which only saves a click. Anything that made the
    selection depend on a script would be dead here and would look exactly like a
    working control.
    """
    await _indexed(client)
    await _ask(client, _SHARED, Strategy.NAIVE_RAG)
    await _ask(client, _OTHER, Strategy.NAIVE_RAG)

    page = (await client.get("/compare")).text
    assert 'action="/compare" method="get"' in page
    assert 'name="naive_rag"' in page
    assert "<button type=\"submit\"" in page

    # Submitting it by hand — which is what the browser does — selects that run.
    older = _options(page, "naive_rag")
    assert older[1].startswith(_SHARED)
    ids = re.findall(
        r'<option value="([^"]+)"',
        re.search(r'<select id="pick-naive_rag"[^>]*>(.*?)</select>', page, re.S).group(1),
    )
    chosen = (await client.get(f"/compare?naive_rag={ids[1]}")).text
    assert _selected(chosen, "naive_rag") == ids[1]
