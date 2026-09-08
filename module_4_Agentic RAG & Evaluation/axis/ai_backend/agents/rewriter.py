"""The Rewriter — turns the question as typed into the question to search for.

**The gap chapter 07 fills and Axis had nothing for.** Axis's only reformulation
happened *inside* the ReAct loop, after retrieval had already failed: the model was
told to "call it with a different phrasing". That is a repair, and it only ever runs
on the escalation path. A follow-up like "How long is it?" does not fail retrieval
because it was phrased badly — it fails because the thing it refers to is in the
previous turn, and no rephrasing of those four words can recover it.

Ported from `reference/chapter_07_enterprise_rag/query_rewriter.py::rewrite_query`,
keeping its four rules, with two changes recorded in
`docs/Axis_Notebook_Alignment.md` §9:

* **Everything downstream sees the rewritten query** — the router and the decomposer
  included. The reference routes on the raw question and applies the rewrite only to
  decomposition, which looks like an oversight rather than a decision: routing on
  text whose abbreviations are expanded and whose pronouns are resolved is strictly
  better information for the same money.
* **`changed` is reported honestly.** The reference returns a string and the caller
  cannot tell a real rewrite from an echo. A card that says "unchanged" when nothing
  needed changing is the difference between a student learning what the rewriter is
  for and a student watching it appear to do nothing.
"""

from __future__ import annotations

from pydantic import BaseModel

from ai_backend.agents.spend import QuerySpend
from ai_backend.contracts.models import Message, Role, StepType
from ai_backend.contracts.pipeline import Turn
from ai_backend.contracts.providers import LLMProvider
from ai_backend.errors import ProviderError
from ai_backend.observability.trace import atrace_step
from ai_backend.textutil import tokenize

MAX_REWRITE_TOKENS = 200

# chapter 07's window: the last three turns, each answer truncated. The rewriter
# needs enough to resolve a pronoun and nothing more — a full transcript would cost
# tokens on every agentic query to no purpose, and the further back a reference
# points the less likely a resolution is to be right.
MAX_HISTORY_TURNS = 3
MAX_HISTORY_ANSWER_CHARS = 200

# Below this many content words, a question is too referential to overlap-check
# against its own resolution — see `_is_plausible`. Two, because one surviving
# stopword-stripped word ("long" in "How long is it?") is not what the question was
# about, so a correct resolution has no reason to carry it.
MIN_CONTENT_WORDS_FOR_OVERLAP = 2

# A rewrite is a search query, not prose. A model that returns a paragraph has
# misunderstood the task, and the excess is dropped rather than embedded.
MAX_REWRITE_CHARS = 300

SYSTEM_PROMPT = """You rewrite a user's question into the query a search index \
should be given. Reply with the query and nothing else — no explanation, no \
quotation marks, no preamble.

Rules:
1. Expand abbreviations and shorthand ("Q3" -> "third quarter", "NTE" -> \
"not-to-exceed").
2. Replace vague references — "it", "that", "the other one" — with the thing they \
refer to, using the conversation so far.
3. Add context the user clearly implied but did not say, such as the document or \
programme under discussion.
4. Do NOT add any constraint the user did not express. Do not narrow the question, \
do not guess at a date or a name that has not been mentioned, and do not answer it.
5. If the question already stands alone and needs no expansion, reply with it \
unchanged."""


class Rewrite(BaseModel):
    """What the rewriter produced, and whether it did anything."""

    text: str
    # False when the model returned the question unchanged, or when the rewrite was
    # skipped or failed. Load-bearing for the canvas card, which says "unchanged"
    # rather than drawing a before-and-after of two identical strings.
    changed: bool = False
    reason: str = ""


class Rewriter:
    """Resolves a question against the conversation. One LLM call, bounded output."""

    def __init__(self, *, llm: LLMProvider) -> None:
        self._llm = llm

    async def rewrite(
        self,
        question: str,
        *,
        spend: QuerySpend,
        history: tuple[Turn, ...] = (),
        enabled: bool = True,
    ) -> Rewrite:
        """Return the query to search for.

        `enabled=False` skips the LLM call and returns the question unchanged, but
        still emits the step — the same reasoning as the Decomposer's `needed=False`
        path. An absent step cannot be told apart from a crash.

        **Never raises.** A provider error or an unparseable completion falls back
        to the original question, because the asymmetry runs one way: a failed
        rewrite costs one wasted LLM call, and a raised one costs the answer. Same
        rule the Router follows for an unreadable classification.
        """
        async with atrace_step(
            StepType.REWRITE,
            label="Rewriter.rewrite",
            raw_input=question,
        ) as step:
            step.set_attribute("original", question)
            step.set_attribute("history_turns", len(history))

            if not enabled:
                step.set_attribute("llm_called", False)
                step.set_attribute("changed", False)
                step.set_output("rewriting is turned off — searching for the question as asked")
                return Rewrite(text=question, reason="rewriting is turned off")

            messages = [
                Message(role=Role.SYSTEM, content=SYSTEM_PROMPT),
                Message(role=Role.USER, content=_prompt_for(question, history)),
            ]

            try:
                spend.reserve_for(messages, max_completion_tokens=MAX_REWRITE_TOKENS)
                completion = await self._llm.complete(
                    messages, max_tokens=MAX_REWRITE_TOKENS, temperature=0.0
                )
            except ProviderError as exc:
                # Recorded, not raised. The query proceeds on the original wording,
                # which is what it would have done without a rewriter at all.
                step.set_attribute("llm_called", True)
                step.set_attribute("changed", False)
                step.set_attribute("fallback_taken", True)
                step.set_output(f"rewrite failed, searching for the question as asked: {exc}")
                return Rewrite(text=question, reason="the rewrite call failed")

            spend.record(completion.usage)
            step.add_usage(completion.usage)
            step.set_output(completion.text)

            rewritten = _parse(completion.text, fallback=question)

            if not _is_plausible(rewritten, question):
                # A "rewrite" with nothing in common with the question is not a
                # rewrite — it is the model having answered, refused, or ignored the
                # instruction. Searching for it would replace the student's question
                # with something they never asked, which is strictly worse than not
                # rewriting at all: the router, the decomposer and retrieval would
                # all then be working on the wrong text, and the trace would show a
                # confident run against a question nobody typed.
                #
                # This is the asymmetry the Router already follows for an unreadable
                # classification, applied to the one stage that can corrupt every
                # stage after it.
                step.set_attribute("rewritten", rewritten)
                step.set_attribute("changed", False)
                step.set_attribute("fallback_taken", True)
                step.set_attribute("implausible", True)
                step.set_output(
                    f"discarded: {rewritten!r} shares no content word with the "
                    f"question, so it is not a rewrite of it. Searching for the "
                    f"question as asked."
                )
                return Rewrite(
                    text=question,
                    reason="the rewrite did not resemble the question",
                )

            changed = _is_different(rewritten, question)

            step.set_attribute("rewritten", rewritten)
            step.set_attribute("changed", changed)
            if not changed:
                step.set_attribute("fallback_taken", rewritten == question)

            return Rewrite(
                text=rewritten,
                changed=changed,
                reason=(
                    "resolved against the conversation"
                    if changed and history
                    else "expanded for retrieval"
                    if changed
                    else "already a standalone query"
                ),
            )


def _prompt_for(question: str, history: tuple[Turn, ...]) -> str:
    """The user turn: the recent conversation, then the question to rewrite.

    History is truncated where it is *read* rather than where it is written, so the
    stored record stays complete while the prompt stays small.
    """
    if not history:
        return f"Question: {question}"

    recent = history[-MAX_HISTORY_TURNS:]
    lines = ["Conversation so far:"]
    for turn in recent:
        answer = turn.answer.strip().replace("\n", " ")
        if len(answer) > MAX_HISTORY_ANSWER_CHARS:
            answer = answer[:MAX_HISTORY_ANSWER_CHARS].rstrip() + "…"
        lines.append(f"Q: {turn.question}")
        lines.append(f"A: {answer}")
    lines.append("")
    lines.append(f"Question: {question}")
    return "\n".join(lines)


def _parse(text: str, *, fallback: str) -> str:
    """The first non-empty line, unwrapped and bounded.

    Models wrap a one-line answer in quotes and occasionally prefix it with
    "Rewritten query:" despite being told not to. Both are stripped; anything
    beyond the first line is discarded, because a rewriter that returned a
    paragraph has produced prose and the paragraph would be embedded as a query.
    """
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        for prefix in ("rewritten query:", "query:", "rewritten:"):
            if line.lower().startswith(prefix):
                line = line[len(prefix) :].strip()
        line = line.strip("\"'` ")
        if line:
            return line[:MAX_REWRITE_CHARS]
    return fallback


def _is_plausible(rewritten: str, original: str) -> bool:
    """Whether this could be a rewrite of that question at all.

    One content word in common is the whole test, using the same tokenizer BM25
    uses (`ai_backend/textutil.py`) so stopwords are stripped: a rewrite expands
    and resolves, so it keeps at least one of the things the question was about.
    A model that returns an answer, a refusal, or a paragraph of prose shares
    nothing, and the caller falls back to the question as typed.

    **Skipped when the question has almost no content words of its own.** This is
    the case the guard has to yield to, and getting it wrong breaks the one pain
    point the rewriter exists for. "How long is it?" tokenizes to `['long']` — a
    single word that a correct resolution ("What is the term of the Master Services
    Agreement?") has no reason to keep, because `long` was never what the question
    was *about*; it was the only word that survived stopword removal. Requiring an
    overlap there rejects every valid resolution of exactly the follow-ups this
    stage exists for.

    So the threshold is `MIN_CONTENT_WORDS_FOR_OVERLAP`, not emptiness. An earlier
    version skipped only when `tokenize(original)` was empty, which never fired for
    "How long is it?" and silently discarded the correct rewrite — the demonstration
    reported "discarded: … shares no content word with the question" while the model
    had done its job perfectly. A referential follow-up shares nothing with its own
    resolution by construction; that is what makes it referential.

    Above the threshold the guard still does its real work: catching a model that
    answered, refused, or returned prose instead of rewriting, which would otherwise
    replace the student's question with something they never asked and leave the
    router, the decomposer and retrieval all working on the wrong text.
    """
    wanted = set(tokenize(original))
    if len(wanted) < MIN_CONTENT_WORDS_FOR_OVERLAP:
        return True
    return bool(wanted & set(tokenize(rewritten)))


def _is_different(rewritten: str, original: str) -> bool:
    """Whether the rewrite is a real change rather than a reformatting.

    Compared case- and punctuation-insensitively on purpose: a model that returns
    "How long is it" for "How long is it?" has changed nothing a retriever can see,
    and a card claiming otherwise would be showing a student a difference that does
    not exist.
    """

    def words(text: str) -> list[str]:
        kept = "".join(c if c.isalnum() else " " for c in text.lower())
        return kept.split()

    return words(rewritten) != words(original)
