"""The recorded verdict on whether each mechanism still earns its cost.

**Why this file exists.** `--compare-strategies` measures four ceilings and exits
non-zero when a mechanism stops paying off. That gate protected nothing on screen: it
printed to a terminal and persisted nothing, so when the decomposition and hop ceilings
went to `+0.00` under a real embedding model, the *Why agentic* page carried on stating
"asked whole, this retrieves neither document" — a sentence the harness was at that moment
contradicting. `demo.py` even documented the invariant it depended on — *"a ceiling is
only in the set once the harness has measured the win"* — and maintained it by hand.

So the verdict is written down, and the page reads it. A card claims a measurement only
when there is a matching record of one.

**The conditions block is the load-bearing half.** A recall figure is not a fact about a
mechanism; it is a fact about one mechanism, one embedding model, one corpus and one
`top_k`. Dropping that context is the whole of how this went wrong: the `0.00` baselines
those questions were chosen on were `FakeEmbeddingProvider` threshold rejections, and
nothing recorded that they were measured under a lexical-overlap embedder. So a report
whose conditions do not match the running settings is treated as **no verdict at all**,
never as a passing one. Switching the embedding provider, moving `top_k`, or editing a
document in `data/` all downgrade the page's claims rather than silently preserving them.

Committed rather than gitignored, for the same reason the search cache is: it is a record
of a measurement someone paid for, and a diff shows exactly what the class will be told.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from ai_backend.config.settings import Settings, get_settings
from ai_backend.evaluation.golden import demo_documents

VERDICT_FILE = Path(__file__).parent / "ceilings.json"


class Conditions(BaseModel):
    """What a recorded measurement is true *of*.

    Every field here has changed at least once in this project's life, and each change
    would have invalidated a recorded figure without touching a line of code.
    """

    embedding_provider: str
    embedding_model: str
    top_k: int
    min_similarity: float
    hybrid: bool
    # The corpus itself, not its filenames: a fixture edited in place is the change most
    # likely to invalidate a measurement and least likely to be noticed. Exactly the edit
    # `data/README.md` warns about.
    corpus: str


class QuestionDelta(BaseModel):
    """One question's score, asked whole against its ground truth."""

    question_id: str
    before: float
    after: float

    @property
    def delta(self) -> float:
        return self.after - self.before

    @property
    def improved(self) -> bool:
        return self.after > self.before


class CeilingVerdict(BaseModel):
    """What one ceiling measured, and whether it demonstrated anything."""

    # `recall` or `coverage` — which measure this ceiling is scored on. Recorded because
    # it is not the same for all four, and a number without its unit is not a
    # measurement.
    unit: str
    improved: int
    eligible: int
    questions: list[QuestionDelta] = Field(default_factory=list)

    @property
    def holds(self) -> bool:
        """Whether this mechanism still earns its cost.

        The same condition the CLI gates on: no eligible question means the golden set
        lost the question the mechanism was demonstrated on, which is a failure and not
        a vacuous pass.
        """
        return self.eligible > 0 and self.improved > 0


class Verdict(BaseModel):
    measured_at: str
    conditions: Conditions
    ceilings: dict[str, CeilingVerdict] = Field(default_factory=dict)


class Trust(StrEnum):
    """Why a card may or may not claim a measurement.

    Four states rather than a boolean, because the remedies differ and a student reading
    "not measured" deserves to know which one they are looking at: run the harness, put
    the settings back, or accept that this corpus no longer demonstrates this.
    """

    VERIFIED = "verified"
    NO_REPORT = "no_report"
    CONDITIONS_CHANGED = "conditions_changed"
    NOT_DEMONSTRABLE = "not_demonstrable"

    @property
    def reason(self) -> str:
        """One sentence, for the card. Written for a student, not an operator."""
        if self is Trust.VERIFIED:
            return ""
        if self is Trust.NO_REPORT:
            return (
                "Nothing has measured this yet on this install — the evaluation harness "
                "records what each mechanism buys, and it has not been run here."
            )
        if self is Trust.CONDITIONS_CHANGED:
            return (
                "The last measurement was taken under different settings or a different "
                "corpus, so its figure is not a claim about this one."
            )
        return (
            "The harness can no longer demonstrate this mechanism on this corpus: asked "
            "whole, retrieval already reaches what splitting the question would reach."
        )


def corpus_fingerprint() -> str:
    """A hash of the corpus as the loader sees it.

    Through `demo_documents()` rather than a fresh glob, so it follows the loader — a
    change to what counts as a corpus document (the `README.md` exclusion, say) moves
    this too, instead of leaving the fingerprint describing a set nothing reads.
    """
    digest = hashlib.sha256()
    for document in sorted(demo_documents(), key=lambda d: d.filename):
        digest.update(document.filename.encode("utf-8"))
        digest.update(document.data)
    return digest.hexdigest()


def conditions_now(settings: Settings | None = None) -> Conditions:
    resolved = settings or get_settings()
    return Conditions(
        embedding_provider=resolved.embedding.provider,
        embedding_model=resolved.embedding.model,
        top_k=resolved.retrieval.top_k,
        min_similarity=resolved.retrieval.min_similarity,
        hybrid=resolved.retrieval.hybrid,
        corpus=corpus_fingerprint(),
    )


def write_verdict(
    ceilings: dict[str, CeilingVerdict],
    *,
    settings: Settings | None = None,
    path: Path | None = None,
) -> Verdict:
    """Record what this run measured, under the conditions it measured it."""
    verdict = Verdict(
        measured_at=datetime.now(UTC).isoformat(timespec="seconds"),
        conditions=conditions_now(settings),
        ceilings=ceilings,
    )
    (path or VERDICT_FILE).write_text(
        json.dumps(verdict.model_dump(), indent=2) + "\n", encoding="utf-8"
    )
    return verdict


def load_verdict(path: Path | None = None) -> Verdict | None:
    """The recorded verdict, or `None` if there is not a readable one.

    A malformed or unreadable file is `None` rather than an exception. This is read on
    the path that renders a page, and the honest answer to "is this claim verified" when
    the record cannot be read is *no* — not a 500.
    """
    target = path or VERDICT_FILE
    if not target.is_file():
        return None
    try:
        return Verdict.model_validate_json(target.read_text(encoding="utf-8"))
    except (ValidationError, ValueError, OSError):
        return None


def trust_for(
    ceiling: str,
    *,
    settings: Settings | None = None,
    verdict: Verdict | None = None,
    path: Path | None = None,
) -> tuple[Trust, CeilingVerdict | None]:
    """Whether this ceiling's measurement may be shown, and the measurement.

    `verdict` is accepted so a caller resolving all four does not re-read and re-hash the
    corpus four times — hashing is cheap but it reads five files, and this runs while a
    page renders.
    """
    record = verdict if verdict is not None else load_verdict(path)
    if record is None:
        return Trust.NO_REPORT, None

    if record.conditions != conditions_now(settings):
        # **Before checking whether it holds**, deliberately. A stale record that happens
        # to say "improved" is the dangerous case: it lies with the authority of a
        # measurement. Mismatched conditions mean there is no measurement of *this*
        # configuration, whatever the numbers say.
        return Trust.CONDITIONS_CHANGED, None

    measured = record.ceilings.get(ceiling)
    if measured is None or not measured.holds:
        return Trust.NOT_DEMONSTRABLE, measured
    return Trust.VERIFIED, measured


__all__ = [
    "CeilingVerdict",
    "Conditions",
    "QuestionDelta",
    "Trust",
    "VERDICT_FILE",
    "Verdict",
    "conditions_now",
    "corpus_fingerprint",
    "load_verdict",
    "trust_for",
    "write_verdict",
]
