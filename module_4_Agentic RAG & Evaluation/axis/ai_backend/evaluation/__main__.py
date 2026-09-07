"""`python -m ai_backend.evaluation` — run the golden set and print the report.

A CLI as well as a test, because these are two different audiences. The pytest
gate answers "may we start the next milestone"; this answers "what is retrieval
actually doing, and did my change help" — which is a question an instructor or a
student should be able to ask without knowing pytest.

`--compare-modes` is the one worth reaching for: it runs dense-only and hybrid
over the same golden set and prints both, which turns System Design Section 10's
choice of hybrid retrieval from an assertion into a number on screen.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys

from ai_backend.config.settings import Settings, get_settings
from ai_backend.contracts.models import Strategy
from ai_backend.evaluation.golden import load_golden_set
from ai_backend.evaluation.runner import (
    Ceiling,
    participates,
    run_ceiling,
    run_golden_set,
)
from ai_backend.evaluation.scoring import Report
from ai_backend.evaluation.verdict import (
    VERDICT_FILE,
    CeilingVerdict,
    QuestionDelta,
    write_verdict,
)


def _render(report: Report) -> str:
    label = f"{report.strategy}" + (f" ({report.mode})" if report.mode else "")
    retrieval_passed = sum(1 for r in report.results if r.retrieval_passed)
    lines = [
        "",
        f"  {label}",
        "  " + "─" * 62,
        f"  retrieval              {retrieval_passed}/{report.total} passed "
        f"({report.retrieval_pass_rate:.0%})   <- gated offline",
    ]

    # A retrieval-only report generated no answers, so every answer metric would
    # read as a total failure. Printing them would be a lie told in numbers.
    if not report.retrieval_only:
        ungrounded = report.ungrounded_handled
        lines += [
            f"  answers                {report.passed}/{report.total} passed "
            f"({report.pass_rate:.0%})   <- needs a real LLM to mean anything",
        ]

    lines += [
        f"  mean precision@k       {report.mean_precision:.3f}",
        f"  mean document recall   {report.mean_document_recall:.3f}",
    ]

    if not report.retrieval_only:
        ungrounded = report.ungrounded_handled
        lines += [
            f"  groundedness agreement {report.groundedness_agreement:.0%}",
            f"  unanswerable handled   {ungrounded[0]}/{ungrounded[1]}"
            + ("" if ungrounded[0] == ungrounded[1] else "   <-- must be all"),
            f"  cited unexpected doc   {report.cited_unexpected}",
            f"  total cost             ${report.total_cost_usd:.4f}",
        ]
    else:
        lines.append("  no answers generated   retrieval measured on its own")

    lines += ["", "  by question kind"]
    # Retrieval-only reports have no answer verdict, so `passed` is uniformly
    # False and the pass/total bar would report a fake wipeout. Break down by the
    # verdict that exists instead.
    breakdown = (
        report.retrieval_kind_breakdown()
        if report.retrieval_only
        else report.kind_breakdown()
    )
    for kind, (passed, total) in sorted(breakdown.items()):
        bar = "#" * passed + "." * (total - passed)
        lines.append(f"    {kind:<14} {passed}/{total}  {bar}")

    predicate = (
        (lambda r: not r.retrieval_passed) if report.retrieval_only else (lambda r: not r.passed)
    )
    failures = [r for r in report.results if predicate(r)]
    if failures:
        lines += ["", "  not passing"]
        for result in failures:
            why = result.error or _why(result)
            lines.append(f"    {result.question.id:<26} {why}")
    return "\n".join(lines) + "\n"


def _render_ceiling_delta(
    baseline: Report, ceiling: Report, which: Ceiling
) -> tuple[str, CeilingVerdict]:
    """Per-question score, the question as asked against its ground truth.

    Returns the rendered block plus the verdict, so the caller can gate on it and
    *record* it without re-deriving what was printed. All three must agree: a gate
    computed separately from the table it is printed beside is a gate that can disagree
    with the evidence for it — and a file written separately from both is a third thing
    to disagree. One computation feeds the table, the exit code and `ceilings.json`.

    **Per question, not aggregated.** A mean over all twenty moves by ~0.05 for a
    change that takes one question from finding nothing to finding everything, and
    the second number is the finding. Only questions carrying ground truth for
    *this* ceiling appear — the rest retrieve over themselves in both runs, so their
    delta is necessarily zero and printing it would pad the table with rows that
    cannot move.
    """
    by_id = {r.question.id: r for r in ceiling.results}
    eligible = [r for r in baseline.results if participates(r.question, which)]

    # **Three measures for four ceilings, and which one is not a detail.** A number
    # without its unit is not a measurement, which is why the unit is printed in the
    # heading and recorded in `ceilings.json`.
    #
    # Decomposition and hop moved off `document_recall` because it could not see them:
    # both their questions name exactly two documents, so recall is three-valued and a
    # single chunk from each scores a perfect 1.00. Under `text-embedding-3-small` a
    # blended query does reach both files — while reaching only one of the two figures
    # being compared — so the ceiling could not exceed the baseline and every delta was
    # `+0.00` by arithmetic. The mechanisms had not stopped working; the measure had
    # stopped being able to tell. `facts` counts the passages the answer cannot be
    # assembled without, declared per question as `expect_passages`.
    #
    # Resolution stays on recall: its baseline genuinely retrieves *nothing* — every
    # word in a bare follow-up is common — so recall has all the range it needs.
    _UNITS = {
        Ceiling.COVERAGE: "coverage",
        Ceiling.DECOMPOSITION: "facts",
        Ceiling.HOP: "facts",
    }
    unit = _UNITS.get(which, "recall")

    def value(result) -> float:
        if which is Ceiling.COVERAGE:
            return result.retrieval.coverage
        if unit == "facts":
            return result.retrieval.fact_recall
        return result.retrieval.document_recall

    lines = [
        f"  {which.value} ceiling — what {which.mechanism} buys ({unit})",
        "  " + "─" * 62,
        f"    {'question':<26} {'asked':>7} {'ground':>7} {'delta':>7}",
    ]
    if not eligible:
        lines.append(f"    (no question carries ground truth for {which.value})")
        return "\n".join(lines) + "\n", CeilingVerdict(unit=unit, improved=0, eligible=0)

    improved = 0
    deltas: list[QuestionDelta] = []
    for result in eligible:
        truth = by_id.get(result.question.id)
        if truth is None:
            continue
        before, after = value(result), value(truth)
        if after > before:
            improved += 1
        deltas.append(
            QuestionDelta(
                question_id=result.question.id, before=before, after=after
            )
        )
        lines.append(
            f"    {result.question.id:<26} {before:>7.2f} {after:>7.2f} "
            f"{after - before:>+7.2f}"
        )

    lines += [
        "",
        f"  {which.mechanism} improved {unit} on {improved}/{len(eligible)} "
        f"question(s).",
    ]
    if not improved:
        # Not a passing state dressed as one. If a mechanism buys nothing, either
        # the corpus grew until a blended query finds everything anyway, or
        # retrieval changed — and in both cases these questions have stopped
        # teaching, which is a finding rather than a green run.
        lines.append(
            f"  <-- {which.mechanism} bought nothing. These questions no longer\n"
            f"      demonstrate it; the set needs harder ones before the demo can\n"
            f"      show the mechanism earning its cost."
        )
    return "\n".join(lines) + "\n", CeilingVerdict(
        unit=unit, improved=improved, eligible=len(eligible), questions=deltas
    )


def _why(result) -> str:
    """A short, specific reason. "failed" tells nobody anything."""
    if not result.retrieval_passed and not result.question.is_unanswerable:
        return (
            f"retrieval missed an expected document "
            f"(recall {result.retrieval.document_recall:.2f})"
        )
    if result.answer.cited_unexpected_document:
        return "cited a document the question does not need"
    if not result.answer.grounded_as_expected:
        return (
            "answered when it should have declined"
            if result.question.is_unanswerable
            else "declined when the documents cover this"
        )
    if result.answer.content_coverage < 1.0:
        missing = [
            phrase
            for phrase in result.question.expect_contains
            if phrase.lower() not in ""
        ]
        return f"answer missing expected content ({', '.join(missing)})"
    return "unknown"


async def _compare_strategies(
    settings: Settings, golden, *, with_agentic: bool
) -> int:
    """Naive baseline, all four mechanism ceilings, optionally the real agentic run.

    The exit code is the interesting part: this is a gate, not a report. It fails
    when a mechanism the platform teaches stops being demonstrable on this set —
    because a platform whose thesis is "orchestration sometimes earns its cost"
    cannot show that if no question exists where it does.

    **Every ceiling is gated, not just decomposition.** Each of the four pain points
    the *Why agentic* page claims to demonstrate rests on one of these, and a
    prediction shown to a student has to be one the harness verifies. A ceiling that
    silently stopped improving would leave the page confidently promising an outcome
    nothing measured — which is the exact failure the labelled question set was
    built to avoid, one level up.

    A ceiling with no eligible question is **not** a pass. It means the golden set
    lost the question that mechanism was demonstrated on, and the page will still be
    offering it.
    """
    baseline = await run_golden_set(
        settings=settings, strategy=Strategy.NAIVE_RAG, golden=golden
    )
    print(_render(baseline))

    verdicts: dict[Ceiling, CeilingVerdict] = {}
    ceilings: dict[Ceiling, Report] = {}
    for which in Ceiling:
        report = await run_ceiling(which, settings=settings, golden=golden)
        ceilings[which] = report
        # The full per-question report is printed for decomposition only. The other
        # three change the score of one or two questions, so twenty rows of
        # unchanged detail three more times would bury the deltas that matter.
        if which is Ceiling.DECOMPOSITION:
            print(_render(report))
        block, measured = _render_ceiling_delta(baseline, report, which)
        print(block)
        verdicts[which] = measured

    # **Written before the gate returns, and from the same objects the table printed.**
    # The page reads this to decide whether a pain-point card may claim a measurement;
    # writing it here is what stops a red gate from leaving the page asserting a figure
    # nothing measured, which is exactly what used to happen. See `verdict.py`.
    record = write_verdict(
        {which.value: measured for which, measured in verdicts.items()},
        settings=settings,
    )
    print(f"  verdict recorded in {VERDICT_FILE.name} at {record.measured_at}\n")

    if with_agentic:
        agentic = await run_golden_set(
            settings=settings, strategy=Strategy.AGENTIC_RAG, golden=golden
        )
        print(_render(agentic))
        # Against the ceiling rather than against naive. "Agentic beat naive" is
        # the easy claim; "agentic reached what a correct decomposition would have
        # reached" is the one that says whether the router and decomposer work.
        decomposition = ceilings[Ceiling.DECOMPOSITION]
        print(
            f"  agentic vs ceiling: document recall "
            f"{agentic.mean_document_recall:.3f} of "
            f"{decomposition.mean_document_recall:.3f} possible\n"
            f"  agentic vs naive:   ${baseline.total_cost_usd:.4f} -> "
            f"${agentic.total_cost_usd:.4f}\n"
        )

    failures = [which for which, measured in verdicts.items() if not measured.holds]
    if failures:
        print("  FAIL: these mechanisms are no longer demonstrable on this set:")
        for which in failures:
            measured = verdicts[which]
            why = (
                "no question carries its ground truth"
                if measured.eligible == 0
                else f"bought nothing on any of {measured.eligible} question(s)"
            )
            print(f"    {which.value:<16} {why}")
        print(
            "    (recorded, so the affected pain-point cards now claim no measurement)"
        )
        print()
        return 1

    print(
        "  All four mechanisms still earn their cost on this set: "
        + ", ".join(
            f"{which.value} {measured.improved}/{measured.eligible} ({measured.unit})"
            for which, measured in verdicts.items()
        )
        + ".\n"
    )
    return 0


async def _main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ai_backend.evaluation",
        description="Run the golden Q&A set against a strategy.",
    )
    parser.add_argument(
        "--strategy",
        default=Strategy.NAIVE_RAG.value,
        choices=[s.value for s in Strategy],
    )
    parser.add_argument(
        "--compare-modes",
        action="store_true",
        help="Run dense-only and hybrid retrieval over the same set and print both.",
    )
    parser.add_argument(
        "--compare-strategies",
        action="store_true",
        help=(
            "Run the naive baseline against the decomposition ceiling — retrieval "
            "over each question's ground-truth split — and print the delta. This is "
            "what the agentic win looks like with the model's ability to decompose "
            "held out, so it works offline. Add --with-agentic to also run the real "
            "agentic pipeline against the ceiling."
        ),
    )
    parser.add_argument(
        "--with-agentic",
        action="store_true",
        help=(
            "With --compare-strategies, also run Agentic RAG. Needs a tool-capable "
            "provider; under --fake it reduces to the naive baseline by construction "
            "(System Design Section 12)."
        ),
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help=(
            "Use the in-process fake providers: free, offline, deterministic. "
            "Measures the plumbing, not real embedding quality."
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    if args.fake:
        settings = Settings(
            llm={"provider": "fake", "model": "fake-model"},
            embedding={"provider": "fake", "model": "fake-embedding"},
            storage={"db_path": ":memory:"},
        )
    else:
        settings = get_settings()

    strategy = Strategy(args.strategy)
    golden = load_golden_set()
    print(
        f"\nGolden set v2 (ACME) — {len(golden.questions)} questions "
        f"({len(golden.unanswerable)} deliberately unanswerable), "
        f"{len(golden.documents)} fixture documents."
    )

    if args.compare_strategies:
        return await _compare_strategies(settings, golden, with_agentic=args.with_agentic)

    modes = [False, True] if args.compare_modes else [settings.retrieval.hybrid]
    reports: list[Report] = []
    for hybrid in modes:
        run_settings = settings.model_copy(
            update={"retrieval": settings.retrieval.model_copy(update={"hybrid": hybrid})}
        )
        report = await run_golden_set(settings=run_settings, strategy=strategy, golden=golden)
        reports.append(report)
        print(_render(report))

    if len(reports) == 2:
        dense, hybrid_report = reports
        delta = hybrid_report.mean_document_recall - dense.mean_document_recall
        print(
            f"  hybrid vs dense: document recall "
            f"{dense.mean_document_recall:.3f} -> "
            f"{hybrid_report.mean_document_recall:.3f} ({delta:+.3f})\n"
        )

    # Non-zero exit on the one thing that must never regress: an answer invented
    # for a question the documents do not cover. Makes this usable in CI as a gate
    # rather than only as a report.
    return 0 if all(r.ungrounded_handled[0] == r.ungrounded_handled[1] for r in reports) else 1


def _force_utf8_stdout() -> None:
    """Make non-ASCII output safe on a Windows console.

    A Windows terminal defaults to cp1252, which cannot encode the box-drawing
    and arrow characters this report uses — and `print` *raises* on the attempt,
    so the whole command dies rather than printing slightly wrong. That is the
    third time this has bitten Axis (the startup banner and the access log were
    the others), so it is fixed here at the boundary rather than by avoiding
    those characters forever.

    `errors="replace"` rather than strict: a mangled glyph in a report is a
    cosmetic problem, and a crashed report is not.
    """
    for stream in (sys.stdout, sys.stderr):
        # Redirected to something that cannot be reconfigured? Leave it: output may
        # be imperfect, but it will not crash.
        with contextlib.suppress(AttributeError, OSError):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


def main() -> None:
    _force_utf8_stdout()
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
