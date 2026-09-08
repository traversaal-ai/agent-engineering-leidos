"""The Milestone 0 gate.

CLAUDE.md: *"Do not start a milestone until the previous one's evaluation slice
passes."* This module is that slice. It runs the golden Q&A set end to end —
ingest four fixture documents across three modalities, ask fifteen questions,
score the results — and asserts floors.

**What is and is not gated here, and why.** The suite runs offline against the
fake providers, which makes retrieval fully real (real parsing, real chunking, a
real index, real cosine similarity) and answer *content* entirely fake — a stub
LLM cannot produce "16 weeks". So:

- retrieval quality, groundedness behaviour, and cost accounting are gated
- answer content coverage is measured and reported, but gated only on a
  real-provider run

A gate asserting content coverage against a stub would fail permanently for a
reason unrelated to the code, and the usual response to a permanently-red gate is
to delete it.

Thresholds are floors set below current measured performance, not targets. They
exist to catch regression, and a floor set at exactly today's number would fail on
any harmless reordering.
"""

from __future__ import annotations

import pytest

from ai_backend.config.settings import Settings
from ai_backend.contracts.models import Strategy
from ai_backend.evaluation.golden import (
    CORPUS_DIR,
    CORPUS_README,
    demo_documents,
    load_golden_set,
)
from ai_backend.evaluation.runner import (
    Ceiling,
    participates,
    run_ceiling,
    run_golden_set,
)
from ai_backend.observability import trace_context
from ai_backend.runtime import build_runtime

pytestmark = pytest.mark.milestone(0)

# **Re-measured for the ACME corpus, from an actual run.** Version 1's floors were
# 0.55 / 0.55 / 0.60 against the synthetic handbook fixtures, where dense scored
# 0.591 recall and hybrid 0.773.
#
# The current figures, `python -m ai_backend.evaluation --fake --compare-modes`:
#
#     dense    retrieval 12/20 (60%)   recall 0.581   precision 0.575
#     hybrid   retrieval 14/20 (70%)   recall 0.738   precision 0.650
#
# Floors sit below the *dense* numbers, since both modes are gated and dense is
# the weaker arm. Deliberately not raised to just under 0.581: eight of the twenty
# questions are *expected* to fail retrieval offline — the three compound questions
# and the multi-hop and conversational ones fail by construction, which is exactly
# what their ceilings measure; `retainage` is in the set because dense fails it;
# and the tabular and visual questions need a real LLM to produce content. A floor
# set tight against a number largely composed of deliberate failures would break on
# any legitimate change to the set.
#
# The order matters here: these were set from the measurement, not tuned until the
# suite went green. A floor adjusted to fit is not a gate.
MIN_DOCUMENT_RECALL = 0.55
MIN_PRECISION = 0.55
MIN_RETRIEVAL_PASS_RATE = 0.55


def _settings(*, hybrid: bool) -> Settings:
    return Settings(
        llm={"provider": "fake", "model": "fake-model"},
        embedding={"provider": "fake", "model": "fake-embedding"},
        storage={"db_path": ":memory:"},
        retrieval={"hybrid": hybrid},
    )


@pytest.fixture(scope="module")
def golden():
    return load_golden_set()


def test_the_demo_corpus_is_on_disk_where_the_loader_looks() -> None:
    """The corpus is a directory of files, and the path to it is a guess until asserted.

    `CORPUS_DIR` is `Path(__file__).resolve().parents[2] / "data"` — two levels of
    directory structure between the loader and its data, and the loader has **no
    fallback** if it is wrong. That is the right choice (a quiet fallback would leave the
    demo button reporting "0 indexed" in front of a class) and it is why this test
    exists: a wrong path has to be a red suite rather than an empty corpus.

    Five, exactly. `AXIS_UPLOAD__MAX_FILES_PER_SESSION` defaults to 5 and bounds the demo
    endpoint too, so a sixth document here is one the endpoint refuses with a 413 —
    `test_loading_the_demo_set_respects_the_file_limit` is the other side of that.
    """
    assert CORPUS_DIR.is_dir(), (
        f"the demo corpus is not at {CORPUS_DIR}, so `Load the demo set` indexes nothing"
    )

    documents = demo_documents()
    assert len(documents) == 5, (
        f"expected the five ACME documents, found {[d.filename for d in documents]}"
    )
    for document in documents:
        assert document.data, f"{document.filename} is empty"
        assert document.filename.endswith(".md")

    # The README is *about* the corpus, not part of it, and it matches the same `*.md`
    # glob. Without the exclusion it indexes as a sixth document and the demo endpoint
    # starts refusing the set it is supposed to load.
    assert (CORPUS_DIR / CORPUS_README).is_file(), (
        "the corpus has no README, so the one edit made to these documents is recorded "
        "nowhere a person editing them would look"
    )
    assert CORPUS_README not in {d.filename for d in documents}, (
        "the README is being indexed as a corpus document"
    )


def test_the_provenance_notice_is_one_line() -> None:
    """**The regression a well-meaning re-copy would cause, silently.**

    Each document opens with a one-line italic notice. The originals in
    `reference/module_3_Enterprise RAG/data/` open with a three-line blockquote instead,
    and it is *identical across all five files* — which made every document's first chunk
    look alike and outrank real content. Module 3 strips it entirely before indexing and
    records the same reason.

    Re-syncing these files from `reference/` raises no error and breaks no request. It
    just makes retrieval quietly worse on the corpus that every measured claim on the
    *Why agentic* page rests on, and the harness would report it as a recall drift with
    no cause attached. So the shape of the notice is asserted here, where the cause is
    named.
    """
    for document in demo_documents():
        text = document.data.decode("utf-8")
        assert "> FICTIONAL SAMPLE DOCUMENT" not in text, (
            f"{document.filename} carries the original three-line blockquote — it looks "
            f"identical in all five files and outranks real content. See data/README.md"
        )
        assert "*Fictional sample document" in text, (
            f"{document.filename} has no provenance notice at all; a fictional corpus "
            f"needs one, it just needs it on one line"
        )


def test_the_golden_set_is_well_formed(golden) -> None:
    """Guards the set itself, so the gate below cannot pass over an empty file.

    Composition is asserted, not just size: System Design Section 12 asks for
    coverage per document type, and the unanswerable questions are what make the
    ungrounded requirement measurable at all.
    """
    assert len(golden.questions) >= 12
    assert len(golden.documents) >= 4

    kinds = {q.kind for q in golden.questions}
    assert {"factual", "lexical", "relational", "unanswerable"} <= kinds, kinds

    # At least three unanswerable, or the groundedness assertions below rest on
    # too small a sample to mean anything.
    assert len(golden.unanswerable) >= 3

    ids = [q.id for q in golden.questions]
    assert len(ids) == len(set(ids)), "question ids must be unique — results key on them"

    # An unanswerable question expecting documents would be self-contradictory.
    for question in golden.unanswerable:
        assert question.expect_documents == []
        assert question.expect_contains == []


def test_all_three_modalities_ingest(golden) -> None:
    """Text, table, and image fixtures all parse.

    Section 12 asks for coverage per document type, which is only meaningful if
    each type actually indexes — a silently-failing xlsx fixture would look like a
    retrieval problem on the tabular questions.
    """
    filenames = {d.filename for d in golden.documents}
    assert any(f.endswith(".md") for f in filenames), filenames
    assert any(f.endswith(".xlsx") for f in filenames), filenames
    assert any(f.endswith(".png") for f in filenames), filenames


@pytest.mark.parametrize("hybrid", [False, True], ids=["dense", "hybrid"])
async def test_retrieval_meets_its_floor(golden, hybrid: bool) -> None:
    """The gate. Both retrieval modes, since both ship at Milestone 0."""
    report = await run_golden_set(
        settings=_settings(hybrid=hybrid),
        strategy=Strategy.NAIVE_RAG,
        golden=golden,
    )

    assert report.total == len(golden.questions)
    assert report.mean_document_recall >= MIN_DOCUMENT_RECALL, (
        f"document recall {report.mean_document_recall:.3f} below floor "
        f"{MIN_DOCUMENT_RECALL}"
    )
    assert report.mean_precision >= MIN_PRECISION, (
        f"precision@k {report.mean_precision:.3f} below floor {MIN_PRECISION}"
    )
    assert report.retrieval_pass_rate >= MIN_RETRIEVAL_PASS_RATE, (
        f"retrieval pass rate {report.retrieval_pass_rate:.0%} below floor "
        f"{MIN_RETRIEVAL_PASS_RATE:.0%}"
    )


@pytest.mark.parametrize("hybrid", [False, True], ids=["dense", "hybrid"])
async def test_every_unanswerable_question_is_declined(golden, hybrid: bool) -> None:
    """The assertion that must never regress, in either retrieval mode.

    An invented answer to a question the documents do not cover is the single most
    damaging thing this platform could produce: a student learning to trust
    citations would learn precisely the wrong lesson.

    Gated across both modes deliberately. Hybrid retrieval broke exactly this and
    the dense-only acceptance tests did not notice, because they never exercise the
    keyword arm — the golden set caught it. Parametrizing here is what stops that
    recurring.
    """
    report = await run_golden_set(
        settings=_settings(hybrid=hybrid),
        strategy=Strategy.NAIVE_RAG,
        golden=golden,
    )

    correct, total = report.ungrounded_handled
    assert total >= 3, "too few unanswerable questions to gate on"
    assert correct == total, (
        f"{total - correct} of {total} unanswerable questions produced an answer "
        f"instead of declining, in {report.mode} mode"
    )


async def test_hybrid_retrieval_never_does_worse_than_dense(golden) -> None:
    """What can honestly be asserted about hybrid retrieval *offline*.

    Not that hybrid wins — that it does not lose. The gate stays the weaker claim
    even though the stronger one currently holds, and the history of this test is
    the reason.

    **What changed with the ACME corpus.** This docstring used to say hybrid's
    advantage was unmeasurable offline, because `FakeEmbeddingProvider` is a hashed
    bag of words using the same tokenizer as BM25 (`ai_backend/textutil.py`), so
    "both retrieval arms measure the same lexical signal" and the delta was exactly
    zero. That was true and the explanation was half right. Measured now:

        dense    document recall 0.581
        hybrid   document recall 0.738     (+0.156)

    The missing variable was the *corpus*, not the provider. Against two topically
    distinct documents, raw term overlap and BM25 do agree. Against five
    interlocking contract documents that share most of their vocabulary they do
    not: BM25's IDF weighting discounts the shared words ("Contractor", "schedule",
    "Sentinel") and finds the rare ones ("retainage", "MSA-2026-0417"), where a bag
    of words counts every match alike. `retainage` is in the golden set for exactly
    this reason — dense finds nothing for it and the keyword arm finds the document.

    **So why is the gate still "never worse"?** Because an earlier version asserted
    `hybrid > dense` and passed only while the fake embedder was accidentally *bad*
    — hashing whole strings, so the dense arm was near-random and almost anything
    beat it. Improving the fake made that assertion fail, which was the right
    outcome: the test had been measuring the stub's defect, not the feature. The
    lesson generalises. The +0.156 above is a property of this corpus's vocabulary,
    and gating on it would make a legitimate corpus change look like a regression.
    The delta belongs in the report, where `--compare-modes` prints it; the gate
    asserts only the thing that must never stop being true.

    Hybrid's advantage against *semantic* embeddings is still a separate and
    stronger measurement, and still a real-provider one:

        AXIS_EMBEDDING__PROVIDER=openai python -m ai_backend.evaluation --compare-modes
    """
    dense = await run_golden_set(
        settings=_settings(hybrid=False), strategy=Strategy.NAIVE_RAG, golden=golden
    )
    hybrid = await run_golden_set(
        settings=_settings(hybrid=True), strategy=Strategy.NAIVE_RAG, golden=golden
    )

    assert hybrid.mean_document_recall >= dense.mean_document_recall, (
        f"hybrid ({hybrid.mean_document_recall:.3f}) retrieved *less* than dense "
        f"({dense.mean_document_recall:.3f}). Fusion should only ever add "
        f"candidates, so this means an arm is dropping results it should keep."
    )
    assert hybrid.mean_precision >= dense.mean_precision * 0.9, (
        "hybrid lost significant precision — the keyword arm's relevance floor "
        "may be too permissive"
    )


@pytest.mark.parametrize("which", list(Ceiling), ids=lambda c: c.value)
async def test_every_mechanism_still_earns_its_cost(golden, which: Ceiling) -> None:
    """One gate per mechanism the *Why agentic* page claims to demonstrate.

    Each of the four pain points rests on one of these ceilings, and a prediction
    shown to a student has to be one the harness verifies — the rule
    `evaluation/demo.py` already sets for the labelled question set, applied to the
    mechanisms rather than to the labels. A ceiling that silently stopped improving
    would leave the page confidently promising an outcome nothing measured.

    Two failure modes, both asserted, and the second is the sneaky one:

    * the mechanism buys nothing on any question that declares its ground truth —
      either retrieval improved until a blended query finds everything anyway, or it
      regressed. Both are findings.
    * **no question declares its ground truth at all.** That is not a pass. It means
      the golden set lost the question the mechanism was demonstrated on, while the
      page carries on offering it. An empty set of eligible questions would make
      "improved on all of them" trivially true, which is how a gate becomes a
      rubber stamp.

    Run in **hybrid**, the stronger retrieval arm, deliberately: a mechanism that
    still earns its cost against the better retriever earns it against the weaker
    one too. It is the harder assertion, and it caught a candidate question that
    improved under dense and not under hybrid.
    """
    settings = _settings(hybrid=True)
    baseline = await run_golden_set(
        settings=settings, strategy=Strategy.NAIVE_RAG, golden=golden
    )
    ceiling = await run_ceiling(which, settings=settings, golden=golden)

    eligible = [r for r in baseline.results if participates(r.question, which)]
    assert eligible, (
        f"no golden question carries ground truth for the {which.value} ceiling, so "
        f"nothing measures {which.mechanism}. The Why-agentic page still offers it."
    )

    truth = {r.question.id: r for r in ceiling.results}

    def value(result) -> float:
        if which is Ceiling.COVERAGE:
            return result.retrieval.coverage
        return result.retrieval.document_recall

    improved = [
        r for r in eligible if value(truth[r.question.id]) > value(r)
    ]
    assert improved, (
        f"{which.mechanism} improved nothing on any of the {len(eligible)} "
        f"question(s) declaring its ground truth. Either the corpus grew until the "
        f"question as asked finds everything anyway, or retrieval changed — in both "
        f"cases those questions have stopped teaching and the set needs harder ones."
    )


async def test_naive_retrieval_reads_a_fraction_of_the_corpus(golden) -> None:
    """The first pain point, as a number rather than an assertion.

    *"Retrieval returns chunks, not the whole picture, and naive RAG is weak at
    synthesizing across many documents"* — the course material's words. This is the
    one pain point document recall is structurally blind to: a summarization
    question can score recall 1.00 having read one chunk of five, because recall
    asks whether the right *document* was reached and not how much of it.

    Measured on the ACME corpus: top-k reaches ~10% of the chunks a summary needs.
    Asserted loosely — below half — because the exact fraction depends on `top_k`
    and on how the corpus chunks, and neither is the point. The point is that the
    gap is large, and that it exists at all.
    """
    settings = _settings(hybrid=True)
    report = await run_golden_set(
        settings=settings, strategy=Strategy.NAIVE_RAG, golden=golden
    )

    covering = [r for r in report.results if r.question.expect_full_coverage]
    assert covering, "no question asks for coverage of its documents"

    for result in covering:
        assert result.retrieval.chunks_available > 0, (
            f"{result.question.id}: the coverage denominator is zero, so the "
            f"measure is not being computed — check that the index can enumerate "
            f"itself (`all_chunks`)"
        )
        assert result.retrieval.coverage < 0.5, (
            f"{result.question.id}: top-k retrieval reached "
            f"{result.retrieval.coverage:.0%} of the corpus, which is too much for "
            f"this question to demonstrate the summarization gap. Either the corpus "
            f"shrank or top_k grew; the question needs a bigger corpus to be about."
        )


async def test_every_question_is_costed(golden) -> None:
    """Cost is attributed, not aggregated after the fact.

    Every answered question carries a non-zero cost, because the fake providers are
    priced non-zero precisely so cost accounting is exercisable. A zero here would
    mean usage is being lost somewhere between the provider and the trace — which
    would make the Compare table's cost column, the whole point of the platform,
    quietly wrong.
    """
    report = await run_golden_set(
        settings=_settings(hybrid=False), strategy=Strategy.NAIVE_RAG, golden=golden
    )

    assert report.total_cost_usd > 0

    for result in report.results:
        # Even a declined question costs an embedding call for the query.
        assert result.answer.cost_usd > 0, f"{result.question.id} recorded no cost"


async def test_relational_questions_are_the_known_weakness(golden) -> None:
    """Records the baseline that decomposition and the hop loop exist to beat.

    Not a failure — a *single* vector search is expected to do badly on a question
    spanning two documents, because one query embedding cannot sit near both. This test
    asserts the weakness is real, so the agentic improvement measured by
    `--compare-strategies` is a delta against something rather than a claim.

    **Reframed, not repurposed.** It used to record this as the premise for graph
    retrieval; graph is a non-goal now (PRD Section 3), but the weakness it documents is
    the same one the decomposition and hop ceilings are measured against — the mechanism
    that answers it changed, the baseline did not.

    If this starts failing because a single search got good at relational questions,
    that is a genuine finding about the corpus and the ceilings deserve rechecking.
    """
    report = await run_golden_set(
        settings=_settings(hybrid=True), strategy=Strategy.NAIVE_RAG, golden=golden
    )

    relational = [r for r in report.results if r.question.kind == "relational"]
    assert relational, "the golden set must contain relational questions"

    passed = sum(1 for r in relational if r.retrieval_passed)
    assert passed < len(relational), (
        "a single vector search now passes every relational question. That is good "
        "news, but it removes the baseline the decomposition and hop ceilings are "
        "measured against — recheck those before ignoring this."
    )


# ---------------------------------------------------------------------------
# The Milestone 1 gate.
#
# Milestone 0's slice above stays as it is — Agentic RAG must not regress it.
# What follows is the claim Milestone 1 actually makes.
# ---------------------------------------------------------------------------


@pytest.mark.milestone(1)
async def test_agentic_rag_does_not_regress_retrieval(golden) -> None:
    """The floor Naive RAG set, held by the strategy that costs three times more.

    Retrieval is the gated metric offline, so this is the real "did Milestone 1
    break anything" check. It is deliberately a floor and not an improvement
    assertion — see the next test for why an improvement cannot be measured here.
    """
    report = await run_golden_set(
        settings=_settings(hybrid=True), golden=golden, strategy=Strategy.AGENTIC_RAG
    )

    assert report.mean_document_recall >= MIN_DOCUMENT_RECALL
    assert report.mean_precision >= MIN_PRECISION
    assert report.retrieval_pass_rate >= MIN_RETRIEVAL_PASS_RATE
    # The unanswerable questions are the ones an agent is most likely to ruin: a
    # loop that keeps rephrasing until something scores above threshold would turn
    # four correct refusals into four fabrications.
    handled, expected = report.ungrounded_handled
    assert handled == expected


@pytest.mark.milestone(1)
async def test_an_agentic_run_costs_more_than_a_single_shot_one(golden) -> None:
    """The orchestration axis, as a number.

    Guards a defect the rest of the suite could not see: the pipeline reported only
    retrieval plus the final answer, so routing and decomposition were charged to
    nobody and both strategies came out at exactly $0.0023. Every acceptance test
    still passed, because none of them read cost.

    An agentic run costing the same as a naive one is not a nice result — it means
    the measurement is broken.
    """
    settings = _settings(hybrid=True)
    naive = await run_golden_set(
        settings=settings, golden=golden, strategy=Strategy.NAIVE_RAG
    )
    agentic = await run_golden_set(
        settings=settings, golden=golden, strategy=Strategy.AGENTIC_RAG
    )

    assert agentic.total_cost_usd > naive.total_cost_usd, (
        f"agentic ${agentic.total_cost_usd} vs naive ${naive.total_cost_usd} — "
        f"routing and decomposition are not being billed to the answer"
    )


@pytest.mark.milestone(1)
async def test_decomposition_finds_documents_the_whole_question_misses(golden) -> None:
    """The claim Milestone 1 makes, and the reason the golden numbers do not show it.

    Agentic RAG scores *identically* to Naive RAG on this set — same recall, same
    precision, same pass rate — while costing 3.3x as much. That looks like the
    milestone achieving nothing, and it would be easy to record it that way and move
    on. It is worth understanding instead.

    The cause is the fake LLM. The router asks for a `COMPLEX`/`SIMPLE`
    classification and gets canned prose, so it correctly falls back to "treat as
    simple", decomposition never fires, and an agentic run reduces to exactly one
    retrieval per question — Naive RAG with two extra billed calls.

    So this test does by hand what a real model would do, on every question in the
    set that carries a ground-truth decomposition. Each names two documents, and a
    single embedding of a question spanning both lands between them and matches
    neither well. Measured on the ACME corpus: +0.50, +0.50 and +1.00, three for
    three — the last from 0.00, because the blended embedding of a two-part
    comparison clears the relevance threshold against nothing at all.

    **The splits are read from the golden set, not held here.** They used to be a
    dict in this test, which meant the ground-truth decomposition lived in two
    places — a `sub_questions` field in the data and a hand-written copy in a test
    — and the copy here was keyed by question id, so it silently stopped matching
    anything when the corpus changed. The test then failed on its own guard rather
    than on the property it exists to check, which is the good outcome of a bad
    design. One source of truth now.

    This is the same limitation Section 12 already records for answer content,
    extended one step: with a stub provider, *retrieval* quality for the agentic
    strategies is also unmeasurable, because the fake cannot do the thinking that
    changes what gets retrieved. The mechanism is gated here; the improvement is
    gated on a real-provider run.
    """
    runtime = build_runtime(_settings(hybrid=True))
    session = "decomposition-probe"
    for document in golden.documents:
        with trace_context(session_id=session, trace_id="ingest"):
            await runtime.ingest(
                scope=session,
                document_id=document.name,
                filename=document.filename,
                data=document.data,
            )

    compound = [q for q in golden.questions if q.is_compound]
    assert len(compound) >= 2, (
        "the compound questions this rests on have gone missing — without at least "
        "two, decomposition has nothing to demonstrate on this set"
    )

    for question in compound:
        wanted = set(question.expect_documents)

        with trace_context(session_id=session, trace_id=question.id):
            whole = await runtime.retriever.retrieve(
                question.question, session_id=session, top_k=5
            )
            found_split: set[str] = set()
            for sub_question in question.sub_questions:
                part = await runtime.retriever.retrieve(
                    sub_question, session_id=session, top_k=5
                )
                found_split |= {c.document_id for c in part.chunks}

        recall_whole = len({c.document_id for c in whole.chunks} & wanted) / len(wanted)
        recall_split = len(found_split & wanted) / len(wanted)

        assert recall_split > recall_whole, (
            f"{question.id}: decomposing changed recall {recall_whole:.2f} -> "
            f"{recall_split:.2f}. If this stops improving, either the retriever or "
            f"the compound questions have drifted, and decomposition has no "
            f"measurable justification left."
        )
        assert recall_split == 1.0, question.id
