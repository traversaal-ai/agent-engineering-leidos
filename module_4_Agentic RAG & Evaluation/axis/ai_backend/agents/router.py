"""The Router — one LLM call, three decisions.

    SOURCE:     DOCUMENTS | WEB | BOTH   — where to look
    COMPLEXITY: SIMPLE | COMPLEX         — one lookup or several
    DEPTH:      SINGLE | MULTI_HOP       — whether a lookup depends on an earlier one

**Why three rather than one.** The reference implementation
(`reference/chapter_07_enterprise_rag/agentic_router.py`) has a single `action` field
naming a source, and leaves sub-query division as an unfinished assignment. Axis has
all three, and they are genuinely independent: a question can be a single lookup
against the web, a three-part question answerable entirely from the uploaded
documents, or a one-part question that cannot be answered until an earlier lookup
names its subject. Collapsing them would mean inferring each from the others, which
is guessing with a label on it. See `docs/Axis_Notebook_Alignment.md` §2.

**`DEPTH` is also a gate, not only a classification.** The ReAct loop was entered
only when retrieval returned nothing, and each iteration stopped the moment a tool
returned anything — both correct for escalation, both wrong for a hop chain, where
the first hop *succeeding* is the precondition for the second. Changing either
unconditionally would alter every existing run, so this field is what makes the new
behaviour opt-in per question: with `SINGLE`, the loop behaves exactly as it did.
The course material predicts this gap by name and hands it to this class —
`docs/Axis_Notebook_Alignment.md` §8.

**The source set is not fixed, and that is what makes the decision honest.** `WEB` is
offered only when a search provider is configured. With `AXIS_SEARCH__PROVIDER=none`
the option is absent from the prompt entirely, because a model told it may search the
web when nothing can will route there confidently and find nothing every time — the
same reason the ReAct loop omits a tool it has no provider for rather than exposing
one that silently returns nothing.

**What it does not decide: the strategy.** The student chose that explicitly, and a
router that overrode the choice would destroy the comparison the platform exists to
teach — asking for Naive RAG and silently getting Agentic RAG teaches the opposite of
the intended lesson.

Section 11 requires an ambiguous query to surface as "Router step shows low-confidence
classification + fallback path taken", which is why `confidence` and `fallback_taken`
are recorded on the step rather than merely influencing behaviour. A student looking at
the trace should be able to see the router was unsure, not infer it from what happened
next.

`reason` is **model-authored** rather than derived in code. It used to be one of two
canned strings, which made it a restatement of the classification rather than a
justification of it. The notebook prints its router's reason and it is the most legible
artefact of a routing decision on a projector — it is the thing a student can disagree
with, which is the whole point of making the decision visible.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel

from ai_backend.agents.spend import QuerySpend
from ai_backend.contracts.models import Message, Role, StepType
from ai_backend.contracts.providers import LLMProvider
from ai_backend.observability.trace import atrace_step

MAX_ROUTE_TOKENS = 200


class Source(StrEnum):
    """Where the pipeline should look.

    `BOTH` exists because the interesting real questions are mixed — "what does our
    policy say and what is the current statutory minimum" needs one of each — and a
    router forced to pick one would drop half the question. It costs both a retrieval
    and a search, which is visible in the trace and in the Compare table.
    """

    DOCUMENTS = "documents"
    WEB = "web"
    BOTH = "both"

    @property
    def uses_documents(self) -> bool:
        return self is not Source.WEB

    @property
    def uses_web(self) -> bool:
        return self is not Source.DOCUMENTS


# Below this the router's own opinion is not worth acting on, so the fallback path
# is taken and recorded. Set where it is because a model hedging at 0.5 on "is this
# one question or two" is telling us it cannot tell, and the cheap branch is the
# right guess when the classifier is guessing.
MIN_CONFIDENCE = 0.5

_CONFIDENCE = re.compile(r"CONFIDENCE:\s*([0-9]*\.?[0-9]+)", re.IGNORECASE)
_SOURCE = re.compile(r"SOURCE:\s*(DOCUMENTS|WEB|BOTH)", re.IGNORECASE)
_REASON = re.compile(r"REASON:\s*(.+)", re.IGNORECASE)
# The *value* after the label, not the word anywhere in the text.
#
# This has to be a field-anchored match rather than a substring search, and the
# reason is a bug this replaced: the earlier version asked for a bare `COMPLEX` or
# `SIMPLE` line and tested `"COMPLEX" in text`. Renaming the field to `COMPLEXITY:`
# made that substring match the *label* — so every answer parsed as complex, and
# every query paid for a decomposition it had not been asked for. Anchoring to
# `COMPLEXITY:` makes the label unmatchable by construction.
_COMPLEXITY = re.compile(r"COMPLEXITY:\s*(COMPLEX|SIMPLE)", re.IGNORECASE)
# Field-anchored for the same reason as COMPLEXITY above, and the trap is identical:
# a substring test for "MULTI_HOP" would match the `DEPTH: SINGLE or MULTI_HOP`
# instruction echoed back by a model that repeats its prompt, so every question
# would route multi-hop and pay for a loop it did not need.
_DEPTH = re.compile(r"DEPTH:\s*(MULTI_HOP|SINGLE)", re.IGNORECASE)

# Trimmed hard. The reason is rendered into a canvas node and read at a glance from
# the back of a room; a model that writes a paragraph gets a sentence of it.
MAX_REASON_CHARS = 160

_DEPTH_RULE = """DEPTH — answer MULTI_HOP when answering needs what the first \
lookup finds in order to know what to look up next: "find X, then find X's Y". The \
giveaway is that the second thing to search for is not named anywhere in the \
question. Answer SINGLE otherwise, including for questions with several parts that \
can each be looked up straight away — those are COMPLEX, not MULTI_HOP."""

_DOCUMENTS_ONLY_PROMPT = f"""You classify how a question about a set of uploaded \
documents should be answered. Reply with exactly four lines and nothing else:

COMPLEXITY: COMPLEX or SIMPLE
DEPTH: SINGLE or MULTI_HOP
CONFIDENCE: <0.0 to 1.0>
REASON: <one short sentence>

Answer COMPLEX when the question has several distinct parts that need looking up \
separately — comparisons, "and" questions spanning different topics, or anything \
requiring two unrelated facts. Answer SIMPLE when one lookup would answer it.

{_DEPTH_RULE}"""

_WITH_WEB_PROMPT = f"""You decide how a question should be answered. Reply with exactly \
five lines and nothing else:

SOURCE: DOCUMENTS or WEB or BOTH
COMPLEXITY: COMPLEX or SIMPLE
DEPTH: SINGLE or MULTI_HOP
CONFIDENCE: <0.0 to 1.0>
REASON: <one short sentence>

SOURCE — where the answer is:
- DOCUMENTS: the user's own uploaded files. Internal policy, their data, anything \
specific to their organisation, and anything that reads like it is about "our" or "my" \
something.
- WEB: current events, recent releases, prices, public facts, anything dated after \
the documents were written, and comparisons of outside products or providers.
- BOTH: the question has one part in each — typically an internal fact and an external \
one that has to be set against it.

Prefer DOCUMENTS when a question could plausibly be answered from the user's own \
material. A wrong guess toward DOCUMENTS costs nothing and shows up as an empty \
search; a wrong guess toward WEB spends money reaching outside material the user can \
check.

COMPLEXITY — answer COMPLEX when the question has several distinct parts that need \
looking up separately. Answer SIMPLE when one lookup would answer it.

{_DEPTH_RULE}"""


class RouteDecision(BaseModel):
    source: Source = Source.DOCUMENTS
    needs_decomposition: bool
    # Whether answering needs a lookup the question itself cannot name — "find X,
    # then find X's Y". Distinct from `needs_decomposition`, and the distinction is
    # the lesson: a *comparison* is several independent lookups all visible in the
    # wording, so splitting finds them; an *inferential* question is one dependent
    # chain, and the second question does not exist until the first is answered, so
    # splitting cannot help.
    #
    # This is also the gate that keeps the loop's behaviour unchanged everywhere
    # else. With SINGLE, the ReAct loop runs exactly as it did before — on empty
    # retrieval only, stopping as soon as a tool returns anything.
    multi_hop: bool = False
    confidence: float
    reason: str
    # True when the model's answer could not be used — unparseable, or too
    # uncertain to act on. Recorded rather than hidden: Section 11 wants the
    # fallback visible.
    fallback_taken: bool = False


class Router:
    """Classifies source and complexity. One LLM call, bounded output."""

    def __init__(self, *, llm: LLMProvider, web_available: bool = False) -> None:
        self._llm = llm
        # The default when `route` is not told otherwise — which is what a caller
        # constructing a Router for one purpose (the evaluation harness, a test) wants.
        self._web_available = web_available

    def system_prompt(self, *, web_available: bool | None = None) -> str:
        return (
            _WITH_WEB_PROMPT
            if (self._web_available if web_available is None else web_available)
            else _DOCUMENTS_ONLY_PROMPT
        )

    async def route(
        self, question: str, *, spend: QuerySpend, web_available: bool | None = None
    ) -> RouteDecision:
        """Classify the question. `web_available` is *this query's* answer.

        **Per call, and that is a change worth explaining**, because the argument
        against it used to be written here: passing it per call would let two calls in
        one query disagree about what sources exist, and a Router routing to `WEB`
        while the loop has no web tool reports a source it never reached.

        That risk is real and the fix is not to fix the flag at construction — it is to
        compute it *once per query* and hand the same value to both. `AgenticRagPipeline.run`
        does exactly that, in one line, before either component is used. What the
        constructor could not express is the student's toggle: whether the web is
        allowed is now a property of the query, not of how the process was started.
        """
        web = self._web_available if web_available is None else web_available
        messages = [
            Message(role=Role.SYSTEM, content=self.system_prompt(web_available=web)),
            Message(role=Role.USER, content=question),
        ]

        async with atrace_step(
            StepType.ROUTE,
            label="Router.route",
            raw_input=question,
            attributes={"web_available": web},
        ) as step:
            spend.reserve_for(messages, max_completion_tokens=MAX_ROUTE_TOKENS)
            completion = await self._llm.complete(
                messages, max_tokens=MAX_ROUTE_TOKENS, temperature=0.0
            )
            spend.record(completion.usage)
            step.add_usage(completion.usage)

            decision = _parse(completion.text, web_available=web)

            step.set_output(completion.text)
            step.set_attribute("source", decision.source.value)
            step.set_attribute("needs_decomposition", decision.needs_decomposition)
            step.set_attribute("multi_hop", decision.multi_hop)
            step.set_attribute("confidence", decision.confidence)
            step.set_attribute("fallback_taken", decision.fallback_taken)
            step.set_attribute("reason", decision.reason)
            return decision


def _parse(text: str, *, web_available: bool) -> RouteDecision:
    """Read the classification, or fall back to the cheap, checkable branch.

    Falling back to DOCUMENTS + SIMPLE on an unreadable answer is deliberate, and the
    argument is the same in both dimensions: the two failure directions are not
    symmetric.

    On complexity — guessing COMPLEX spends LLM calls decomposing a question that did
    not need it, on every query where the router misbehaves. Guessing SIMPLE spends
    nothing extra and, if wrong, produces an answer from one retrieval instead of
    several — visibly worse in the trace, which is the failure a student can learn
    from.

    On source — guessing WEB spends money at a third party for material the student
    cannot verify against their own documents, and drags the prompt-injection surface
    in with it. Guessing DOCUMENTS is free and fails as an empty retrieval, which the
    pipeline already renders as a visible step.
    """
    complexity = _COMPLEXITY.search(text)
    said_complex = bool(complexity) and complexity.group(1).upper() == "COMPLEX"
    complexity_read = complexity is not None

    # **Read, but not required.** An unreadable DEPTH falls back to SINGLE on its
    # own rather than dragging SOURCE and COMPLEXITY down with it, which is the one
    # place this dimension is treated differently from the other two — and it is a
    # deliberate asymmetry rather than an inconsistency. SINGLE is exactly what the
    # router said before this field existed, so a model that omits the line produces
    # the behaviour every run had until now. Failing the whole classification over
    # it would make a missing fourth line more damaging than never having asked for
    # it, and would regress every prompt a fine-tuned or older model responds to.
    depth = _DEPTH.search(text)
    said_multi_hop = bool(depth) and depth.group(1).upper() == "MULTI_HOP"

    match = _CONFIDENCE.search(text)
    confidence = float(match.group(1)) if match else 0.0
    # A model is welcome to report 0.95; it is not welcome to report 3.
    confidence = max(0.0, min(1.0, confidence))

    source, source_read = _parse_source(text, web_available=web_available)
    reason = _parse_reason(text)

    if not complexity_read or not source_read:
        # No usable classification in at least one dimension. Both fall back
        # together: a decision half-read is a decision not made, and acting on the
        # readable half would produce a run whose trace says the router decided
        # something it did not.
        return RouteDecision(
            source=Source.DOCUMENTS,
            needs_decomposition=False,
            multi_hop=False,
            confidence=confidence,
            reason=reason
            or (
                "router returned no usable classification; treating as a simple "
                "document lookup"
            ),
            fallback_taken=True,
        )

    if confidence < MIN_CONFIDENCE:
        return RouteDecision(
            source=Source.DOCUMENTS,
            needs_decomposition=False,
            multi_hop=False,
            confidence=confidence,
            reason=(
                f"router answered at confidence {confidence:.2f}, below the "
                f"{MIN_CONFIDENCE} threshold; treating as a simple document lookup"
            ),
            fallback_taken=True,
        )

    return RouteDecision(
        source=source,
        needs_decomposition=said_complex,
        multi_hop=said_multi_hop,
        confidence=confidence,
        reason=reason
        or (
            "needs a chained lookup"
            if said_multi_hop
            else "multi-part question"
            if said_complex
            else "single lookup"
        ),
    )


def _parse_source(text: str, *, web_available: bool) -> tuple[Source, bool]:
    """The source, and whether one was actually stated.

    When no search provider is configured the prompt never asked for a SOURCE line,
    so its absence is expected rather than a parse failure — hence the `True` in that
    branch. Reporting it as unread would make every documents-only run record
    `fallback_taken`, which would then mean nothing.
    """
    if not web_available:
        return Source.DOCUMENTS, True

    match = _SOURCE.search(text)
    if not match:
        return Source.DOCUMENTS, False
    return Source(match.group(1).lower()), True


def _parse_reason(text: str) -> str:
    match = _REASON.search(text)
    if not match:
        return ""
    # First line only: the pattern is greedy to the newline, but a model that ignores
    # "one short sentence" and writes three lines would otherwise put the rest into
    # the following lines, which are not matched — this is belt and braces for the
    # case where it uses no newline at all.
    reason = match.group(1).strip().splitlines()[0].strip()
    return reason[:MAX_REASON_CHARS]
