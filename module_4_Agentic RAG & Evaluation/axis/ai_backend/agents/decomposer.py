"""The Decomposer — splits a multi-part question into separately-retrievable parts.

**The step is emitted unconditionally, even when nothing is decomposed.** Two of
Milestone 1's acceptance criteria assert `decompose` appears in an agentic trace,
and beyond satisfying them, an absent step is an ambiguous signal: a student cannot
tell "the router decided this was simple" from "decomposition crashed" from "this
build does not decompose". A step saying `sub_questions: 1, reason: router
classified this as simple` says which.
"""

from __future__ import annotations

from ai_backend.agents.spend import QuerySpend
from ai_backend.contracts.models import Message, Role, StepType
from ai_backend.contracts.providers import LLMProvider
from ai_backend.observability.trace import atrace_step

MAX_DECOMPOSE_TOKENS = 200

# Each sub-question costs a retrieval, and every retrieved chunk competes for space
# in the synthesis prompt. A model asked to split a question will occasionally
# produce a dozen; bounding it keeps the cost of a bad completion proportionate.
MAX_SUB_QUESTIONS = 4

SYSTEM_PROMPT = """You split a question into the smallest set of standalone \
sub-questions that together answer it. Reply with one sub-question per line and \
nothing else — no numbering, no preamble, no blank lines.

Each sub-question must stand alone: replace pronouns and references with the thing \
they refer to, so it can be searched on its own. Produce at most 4. If the question \
is already a single lookup, reply with the question unchanged."""


class Decomposer:
    """Breaks a question into sub-questions. One LLM call, bounded output."""

    def __init__(self, *, llm: LLMProvider) -> None:
        self._llm = llm

    async def decompose(
        self, question: str, *, spend: QuerySpend, needed: bool, reason: str
    ) -> list[str]:
        """Return the sub-questions to retrieve for.

        `needed=False` skips the LLM call and returns the original question, but
        still emits the step. Paying for a decomposition the router just said was
        unnecessary would make the router pointless.
        """
        async with atrace_step(
            StepType.DECOMPOSE,
            label="Decomposer.decompose",
            raw_input=question,
        ) as step:
            if not needed:
                step.set_attribute("llm_called", False)
                step.set_attribute("sub_questions", 1)
                step.set_attribute("sub_questions_text", [question])
                step.set_attribute("reason", reason)
                step.set_output(f"not decomposed — {reason}")
                return [question]

            messages = [
                Message(role=Role.SYSTEM, content=SYSTEM_PROMPT),
                Message(role=Role.USER, content=question),
            ]
            spend.reserve_for(messages, max_completion_tokens=MAX_DECOMPOSE_TOKENS)
            completion = await self._llm.complete(
                messages, max_tokens=MAX_DECOMPOSE_TOKENS, temperature=0.0
            )
            spend.record(completion.usage)
            step.add_usage(completion.usage)

            parts = _parse(completion.text, fallback=question)
            truncated = len(parts) > MAX_SUB_QUESTIONS
            parts = parts[:MAX_SUB_QUESTIONS]

            step.set_output(completion.text)
            step.set_attribute("llm_called", True)
            step.set_attribute("sub_questions", len(parts))
            # The parsed list, not just how many. This is the most interesting single
            # artefact an agentic run produces — the question the student asked, split
            # into the questions the system actually went looking for — and until now
            # it survived only inside `raw_output`, as the model's unparsed text.
            #
            # Structured here rather than parsed by the client for the same reason
            # `retrieved` is structured on the RETRIEVE step: a client parsing
            # `raw_output` would be re-implementing `_parse` and would drift from it
            # the first time the prompt or the stripping rules changed.
            step.set_attribute("sub_questions_text", list(parts))
            if truncated:
                # Never silently. A dropped sub-question is a fact about why the
                # answer is incomplete, and it belongs in the trace.
                step.set_attribute("truncated_to", MAX_SUB_QUESTIONS)
            if parts == [question]:
                step.set_attribute("fallback_taken", True)
            return parts


def _parse(text: str, *, fallback: str) -> list[str]:
    """One sub-question per line, with the obvious list decorations stripped.

    Falls back to the original question rather than raising. A decomposer that
    fails should cost the query one wasted LLM call, not the answer.
    """
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Models add "1. ", "- ", "* " despite being told not to.
        line = line.lstrip("0123456789.)-* \t").strip()
        if line:
            lines.append(line)

    return lines or [fallback]
