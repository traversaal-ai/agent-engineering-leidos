"""Plain-language explanations of trace steps, generated on demand.

The raw trace is authentic and, for a student meeting retrieval for the first time,
largely opaque: `VectorRetriever.retrieve` / `'parental leave', top_k=5` /
`3 chunks above threshold (0.81, 0.77, 0.71)` is precise and explains nothing. The
narrated view is the same data in a sentence.

Two properties, both from PRD Section 6's criterion, and both structural rather
than incidental:

**Lazy and cached per step.** Narrating a whole trace up front would charge a
student for explanations of steps they never opened — and an agentic trace has a
dozen steps. The narration is generated on first toggle and written back onto the
step, so the second toggle is free. This is why the cost of the narrated view scales
with curiosity rather than with trace length.

**Written through the store.** `store.set_narration` redacts, so a key echoed back
in a provider error and quoted into a narration is scrubbed on the way to disk.
Returning the provider's text directly to the caller instead would bypass that —
which is exactly the leak the acceptance test plants a key to catch. So this module
does not return what it generated; it re-reads what was stored.
"""

from __future__ import annotations

from ai_backend.contracts.models import AgentStep, Message, Role, StepType
from ai_backend.contracts.providers import LLMProvider
from ai_backend.observability.trace import atrace_step

MAX_NARRATION_TOKENS = 200

SYSTEM_PROMPT = """You explain one step of a retrieval-augmented generation trace \
to a student who is new to the subject.

Two or three sentences. Say what this step did and why that step exists in the \
pipeline. Use the numbers from the step — durations, costs, how many passages were \
found — because those are what the student is looking at.

Plain language. No bullet points, no headings, no restating the field names."""

# What each step type is *for*, supplied to the model rather than left to it. A model
# asked to explain "step_type: route" will invent a plausible purpose, and a
# plausible-but-wrong explanation of how the pipeline works is worse than none in a
# teaching tool — the student cannot tell it is wrong.
_PURPOSE = {
    StepType.ROUTE: (
        "The router makes two decisions: which source to use — the uploaded documents, "
        "the web, or both — and whether the question is one lookup or several. Only "
        "the agentic strategies do this; a single-shot strategy always searches the "
        "documents once. The web option is offered only when a search provider is "
        "configured."
    ),
    StepType.SEARCH_WEB: (
        "A web search. Unlike retrieval, this is a paid request to a third party and "
        "it returns short snippets of text nobody has vetted — so an answer built on "
        "it is grounded in the public web rather than in the student's own documents, "
        "which is why those citations are marked differently."
    ),
    StepType.DECOMPOSE: (
        "The decomposer splits a multi-part question into standalone sub-questions "
        "so each can be searched for separately."
    ),
    StepType.RETRIEVE: (
        "Retrieval embeds the query and finds the most similar passages in the "
        "index — the student's own uploaded documents, searched locally and for free. "
        "Passages below a relevance threshold are discarded rather than passed on, "
        "which is why this step can legitimately find nothing, and why Axis says so "
        "instead of letting the model guess."
    ),
    StepType.ITERATE: (
        "One turn of the agent loop: the model decides what to do next, having seen "
        "that the direct search failed. Its tool calls are the steps nested beneath."
    ),
    StepType.CALL_TOOL: (
        "The agent invoked a tool, with a query it chose itself. There are two: "
        "document search, which is free, and web search, which costs money per call "
        "and is only offered when a search provider is configured."
    ),
    StepType.SYNTHESIZE: (
        "Synthesis writes the final answer from the retrieved passages, and is told "
        "to cite each claim. Passages below the relevance threshold never reach it, "
        "and an answer that cites nothing is withheld rather than shown — which is "
        "why this step can legitimately refuse to answer a question the model could "
        "have guessed at."
    ),
    StepType.EMBED: (
        "Text was converted into a vector so it can be compared by similarity. This "
        "is a paid call to the embedding provider."
    ),
    StepType.GENERATE: (
        "A call to the language model. The tokens and cost recorded here are what "
        "the provider actually charged for."
    ),
    StepType.INGEST: (
        "A document was parsed and indexed, which is what makes it searchable."
    ),
    StepType.SUMMARIZE: (
        "Part of a summary. Summarizing reads every document rather than searching for "
        "the relevant part, so it happens once per document and then once more to "
        "combine them — which is why its cost grows with how much was uploaded, where "
        "a question's cost does not."
    ),
}


def describe(step: AgentStep) -> str:
    """The step rendered as prompt material.

    Deliberately includes the identifying detail — label, type, timings — because
    the narration must differ between two steps of the same kind. The fake provider
    repeats its last response verbatim, so a narration built only from the model's
    text would be identical for every step in a trace and the cache would look like
    it was serving the wrong entry.
    """
    lines = [
        f"Step type: {step.step_type}",
        f"Component: {step.label or 'unnamed'}",
        f"Status: {step.status}",
        f"Duration: {step.duration_ms} ms",
    ]
    if step.usage.total_tokens:
        lines.append(
            f"Tokens: {step.usage.prompt_tokens} in, "
            f"{step.usage.completion_tokens} out, cost ${step.usage.cost_usd}"
        )
    if step.raw_input:
        lines.append(f"Input: {step.raw_input[:400]}")
    if step.raw_output:
        lines.append(f"Output: {step.raw_output[:400]}")
    if step.attributes:
        lines.append(f"Recorded details: {step.attributes}")
    if step.error:
        lines.append(f"Error: {step.error}")

    purpose = _PURPOSE.get(step.step_type)
    if purpose:
        lines.append(f"What this kind of step is for: {purpose}")
    return "\n".join(lines)


async def narrate(step: AgentStep, *, llm: LLMProvider) -> str:
    """Generate one step's narration. One LLM call, bounded.

    Traced like any other provider call — the cost of narration is real and belongs
    in the session total rather than being quietly excluded because it was the
    student's own request.
    """
    messages = [
        Message(role=Role.SYSTEM, content=SYSTEM_PROMPT),
        Message(role=Role.USER, content=describe(step)),
    ]

    async with atrace_step(
        StepType.NARRATE,
        label="Narrator.narrate",
        raw_input=f"{step.step_type} step {step.id}",
        attributes={"narrated_step_id": step.id, "narrated_step_type": str(step.step_type)},
    ) as trace:
        completion = await llm.complete(
            messages, max_tokens=MAX_NARRATION_TOKENS, temperature=0.3
        )
        trace.add_usage(completion.usage)
        trace.set_output(completion.text)

    text = completion.text.strip()
    if not text:
        # A model returning nothing must not produce an empty narrated pane, which
        # reads as a broken feature rather than a failed call.
        return f"This step ran {step.label or step.step_type} in {step.duration_ms} ms."

    # Prefixed with what the step was. Two purposes: the student gets the anchor
    # before the explanation, and two steps of the same type narrate differently
    # even when a provider returns identical prose — which the per-step caching
    # criterion requires be observable.
    return f"{_headline(step)} {text}"


def _headline(step: AgentStep) -> str:
    # ASCII only. Narration is written to SQLite, echoed by the evaluation CLI, and
    # printed by anything driving the API from a terminal — and on Windows the
    # default console encoding is cp1252, which has already produced three
    # `UnicodeEncodeError` crashes in this project from characters that looked
    # harmless in a source file.
    where = step.label or str(step.step_type)
    return f"[{step.step_type} / {where}]"
