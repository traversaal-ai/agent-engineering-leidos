"""The comparison verdict — the one sentence the panel exists for.

Everything else in that panel is evidence; the verdict is the finding. Worth its own
module because the logic is entirely about *judgement* — which of several true
statements to make about a pair of runs — and the failure mode is not a crash but a
sentence that is subtly wrong about what happened.

The case that matters most is the unflattering one. Both strategies routinely cite the
same passages, so "agentic paid 2x and reached the same source" is the common outcome
and it is the lesson, not a result to soften. A verdict that hedged there would make
the panel useless exactly when it has something to say.
"""

from __future__ import annotations

from frontend.app import _comparison_rows, _verdict


def _run(**overrides) -> dict:
    base = {
        "label": "Naive RAG",
        "strategy": "naive_rag",
        "ran": True,
        "grounded": True,
        "documents": ["handbook.md"],
        "sub_questions": 1,
        "iterations": 0,
        "retrievals": 1,
        "llm_calls": 1,
        "passages": 3,
        "latency_ms": 3593,
        "cost_usd": 0.000081,
        "citations": 2,
    }
    base.update(overrides)
    return base


def _agentic(**overrides) -> dict:
    # Merged rather than passed alongside `**overrides`, so a test can override any of
    # these without a duplicate-keyword TypeError.
    defaults = {
        "label": "Agentic RAG",
        "strategy": "agentic_rag",
        "sub_questions": 2,
        "iterations": 1,
        "retrievals": 4,
        "llm_calls": 3,
        "passages": 13,
        "latency_ms": 9749,
        "cost_usd": 0.000159,
    }
    return _run(**{**defaults, **overrides})


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------


def test_one_run_has_nothing_to_compare() -> None:
    """No verdict until there are two runs.

    The panel still renders — one filled column beside one visibly waiting is what
    prompts the second ask — but inventing a comparison from a single data point
    would be worse than saying nothing.
    """
    assert _verdict([_run()]) is None
    assert _verdict([]) is None


def test_the_same_sources_for_more_money_is_stated_plainly() -> None:
    """The common case, and the one worth getting right.

    Both strategies cite the same document, so the extra orchestration covered no
    new ground on this question. That is the finding. The old table showed '2 cited'
    against '2 cited' and left the reader to infer it — or to assume the measurement
    was broken.
    """
    verdict = _verdict([_run(), _agentic()])

    assert verdict is not None
    assert "same" in verdict.lower()
    assert "2.0x" in verdict, f"the cost ratio should be stated: {verdict}"


def test_the_verdict_never_claims_the_answers_are_the_same() -> None:
    """The verdict may only claim what the comparison measures.

    Nothing in `_record_run` reads the answer text — it records which *documents*
    were cited. So "reached the same sources" is a finding and "did not change the
    answer" is an inference, and the second is not available from the first: two
    answers citing the same two documents can differ in what they extract, how
    completely, and how precisely they attribute it.

    This is asserted as an absence because the failure is a sentence that reads
    perfectly well and is unsupported — exactly the kind that survives review. A
    real quality verdict needs `evaluation/scoring.py` behind it, which is
    Milestone 3's cross-strategy report.
    """
    verdicts = [
        _verdict([_run(), _agentic()]),
        _verdict(
            [_run(documents=["handbook.md"]), _agentic(documents=["handbook.md", "security.md"])]
        ),
        _verdict([_run(grounded=False), _agentic()]),
        _verdict([_run(), _agentic(grounded=False)]),
    ]

    for verdict in verdicts:
        assert verdict is not None
        lowered = verdict.lower()
        for overclaim in ("did not change the answer", "the same answer", "answers match"):
            assert overclaim not in lowered, (
                f"the verdict characterises answer content it never read: {verdict}"
            )


def test_reaching_a_document_the_cheaper_run_missed_is_named() -> None:
    """The win case. Naming the document is what makes it checkable."""
    verdict = _verdict(
        [_run(documents=["handbook.md"]), _agentic(documents=["handbook.md", "security.md"])]
    )

    assert verdict is not None
    assert "security.md" in verdict
    assert "missed" in verdict


def test_fewer_sources_for_more_money_is_flagged_not_excused() -> None:
    """Agentic reaching *less* than naive is a bug signal, not a trade-off.

    It would be easy to phrase this as though it were a legitimate outcome. It is
    not — the agentic path retrieves a superset by construction, so this means
    something is wrong, and the verdict should say to look.
    """
    verdict = _verdict(
        [_run(documents=["handbook.md", "security.md"]), _agentic(documents=["handbook.md"])]
    )

    assert verdict is not None
    assert "fewer" in verdict
    assert "investigating" in verdict


def test_disjoint_sources_defer_to_the_reader() -> None:
    """Different documents cited is not automatically better or worse.

    Nothing here can rank two grounded answers from different sources, so the honest
    verdict points at the answers rather than pretending to a judgement.
    """
    verdict = _verdict([_run(documents=["handbook.md"]), _agentic(documents=["security.md"])])

    assert verdict is not None
    assert "different sources" in verdict


def test_an_ungrounded_agentic_run_against_a_grounded_cheap_one() -> None:
    verdict = _verdict([_run(), _agentic(grounded=False, documents=[])])

    assert verdict is not None
    assert "found nothing to cite" in verdict
    assert "did not help" in verdict


def test_the_agentic_run_earning_its_cost_is_credited() -> None:
    """The case that justifies the whole feature existing."""
    verdict = _verdict([_run(grounded=False, documents=[]), _agentic()])

    assert verdict is not None
    assert "answered where" in verdict
    assert "produced an answer at all" in verdict


def test_neither_grounded_says_so_about_the_documents() -> None:
    verdict = _verdict([_run(grounded=False, documents=[]), _agentic(grounded=False, documents=[])])

    assert verdict is not None
    assert "do not cover this" in verdict


def test_a_free_run_does_not_produce_a_cost_ratio() -> None:
    """No division by zero.

    A run against the fake providers, or one that took the ungrounded path and made
    no LLM call at all, costs nothing. `x / 0` here would take down the whole result
    panel — including the answer, which is fine — for a decoration.
    """
    verdict = _verdict([_run(cost_usd=0.0), _agentic(cost_usd=0.0)])

    assert verdict is not None
    assert "comparable cost" in verdict


# ---------------------------------------------------------------------------
# The rows and their ratios
# ---------------------------------------------------------------------------


def test_ratios_are_computed_against_the_smaller_value() -> None:
    """Always a number greater than one, so the column reads consistently.

    Dividing in a fixed strategy order would give 4.0x on one row and 0.25x on
    another depending on which way the metric happened to fall, and a column mixing
    both is unreadable at a glance.
    """
    rows = {r["label"]: r for r in _comparison_rows([_run(), _agentic()])}

    assert rows["retrievals"]["ratio"] == 4.0
    assert rows["llm calls"]["ratio"] == 3.0
    assert rows["passages seen"]["ratio"] > 4.0
    assert rows["latency"]["ratio"] > 2.5


def test_an_equal_metric_reports_no_ratio() -> None:
    """`None`, which the template renders as "same".

    "1.0x" is technically true and reads as though something differed.
    """
    rows = {r["label"]: r for r in _comparison_rows([_run(), _agentic(citations=2)])}

    assert rows["citations"]["ratio"] is None


def test_a_zero_value_reports_no_ratio_rather_than_dividing() -> None:
    """A naive run makes no tool calls and may make no retrievals worth counting.

    The guard is on the *denominator* being zero, not on the values being unequal —
    0 and 4 are unequal and still have no meaningful ratio.
    """
    rows = {r["label"]: r for r in _comparison_rows([_run(retrievals=0), _agentic()])}

    assert rows["retrievals"]["ratio"] is None
    assert [c["value"] for c in rows["retrievals"]["cells"]] == [0, 4]


def test_the_table_shows_the_mechanism_and_not_only_its_consequences() -> None:
    """Sub-questions and escalations are rows, not just implied by the cost.

    The table used to carry every consequence of splitting a question — more
    retrievals, more LLM calls, more passages, more money — and nothing saying the
    question had been split. So "agentic did more work" was visible and *why* was
    not, which reads as unexplained overhead rather than as a mechanism a student
    can decide is worth it.

    `escalations` is the same omission one level down: `_record_run` has counted
    `iterations` since Milestone 2 and never displayed it, which hid the one part of
    agentic cost that is not fixed overhead.
    """
    rows = {r["label"]: r for r in _comparison_rows([_run(), _agentic(sub_questions=3)])}

    assert "sub-questions" in rows, sorted(rows)
    assert [c["value"] for c in rows["sub-questions"]["cells"]] == [1, 3]
    assert "escalations" in rows, sorted(rows)

    # The mechanism reads before its consequences.
    labels = [r["label"] for r in _comparison_rows([_run(), _agentic()])]
    assert labels.index("sub-questions") < labels.index("cost")


def test_a_naive_run_reports_one_sub_question_rather_than_zero() -> None:
    """Naive emits no decompose step, and 1 is the honest reading of that.

    Zero would say it asked nothing. It asked one question — that is the whole
    definition of single-shot — and a 0-vs-3 row would also suppress the ratio,
    losing the "3x the questions asked" figure that is the point of the row.
    """
    rows = {r["label"]: r for r in _comparison_rows([_run(), _agentic(sub_questions=3)])}

    assert rows["sub-questions"]["ratio"] == 3.0


def test_rows_are_keyed_so_jinja_can_read_them() -> None:
    """A guard for a bug that took down the whole result panel.

    The cell list was called `values`, and `row.values` in Jinja resolves to the
    dict's own `.values` *method* rather than the key — so the template iterated a
    bound method and raised `TypeError`. `items` and `keys` are the same trap.
    """
    for row in _comparison_rows([_run(), _agentic()]):
        assert "cells" in row
        for reserved in ("values", "items", "keys", "get"):
            assert reserved not in row, (
                f"{reserved!r} collides with a dict method and will not survive Jinja"
            )
