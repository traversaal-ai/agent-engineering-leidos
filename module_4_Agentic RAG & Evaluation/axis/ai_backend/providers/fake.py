"""Deterministic in-process providers. No network, no keys, no cost.

These are not a testing afterthought — they are what makes the acceptance suite
meaningful. Two properties matter:

**`call_count` is the assertion that gives the cost-cap criterion teeth.** PRD
Section 6 requires a capped session be rejected "before any LLM call is made".
You cannot prove a negative like that by inspecting a response body; you prove it
by asserting the provider was never reached. That is the difference between
testing the error message and testing the behaviour.

**Determinism keeps the suite honest.** PRD Section 7 lists non-deterministic
output as a live risk. A test that calls a real model is a test that fails on
Tuesday for reasons nobody can reproduce, so nothing in `tests/` ever does.

`fail_after` and `latency_ms` exist so the failure modes in System Design
Section 11 can be exercised deliberately rather than waited for.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import AsyncIterator, Sequence
from decimal import Decimal

from ai_backend.contracts.models import (
    Caption,
    Completion,
    CompletionChunk,
    EmbeddingResult,
    FinishReason,
    Message,
    Role,
    SearchResult,
    StepType,
    ToolCall,
    ToolSpec,
    Usage,
    WebSource,
)
from ai_backend.errors import ProviderError
from ai_backend.observability.trace import traced
from ai_backend.providers import pricing
from ai_backend.providers.base import embedding_attributes
from ai_backend.textutil import tokenize

FAKE_LLM_MODEL = "fake-model"
FAKE_EMBEDDING_MODEL = "fake-embedding"


# Named so `complete` can tell "nobody scripted this" from "somebody scripted
# exactly this", which is what lets the rewrite echo below defer to a test that
# wants a specific rewrite.
_DEFAULT_RESPONSES = ("This is a fake answer [1].",)

# The Rewriter's prompt, identified by two phrases from it. Matching on the prompt
# rather than on a flag passed in, because the double should behave correctly for
# any caller — including one written later that nobody thought to tell it about.
_REWRITE_MARKERS = ("rewrite a user's question", "query a search index")


def _asks_for_a_rewrite(messages: Sequence[Message]) -> bool:
    system = " ".join(m.content.lower() for m in messages if m.role is Role.SYSTEM)
    return any(marker in system for marker in _REWRITE_MARKERS)


def _last_question(messages: Sequence[Message]) -> str:
    """The question out of a rewrite prompt's user turn.

    The turn is either "Question: <text>" or a short transcript ending in that
    line, so the last `Question:` is the one being asked about.
    """
    for message in reversed(messages):
        if message.role is not Role.USER:
            continue
        for line in reversed(message.content.splitlines()):
            if line.strip().lower().startswith("question:"):
                return line.split(":", 1)[1].strip()
    return ""


class FakeLLMProvider:
    """A scriptable LLM.

    `responses` is consumed in order; once exhausted it repeats the last entry,
    so a test that only cares about the first answer need not script every call
    an agent loop might make.
    """

    name = "fake"

    def __init__(
        self,
        *,
        model: str = FAKE_LLM_MODEL,
        responses: Sequence[str] | None = None,
        tool_calls: Sequence[Sequence[ToolCall]] | None = None,
        rewrite: str | None = None,
        fail_after: int | None = None,
        latency_ms: int = 0,
        prompt_tokens: int = 100,
        completion_tokens: int = 50,
    ) -> None:
        self.model = model
        # The default answer carries a citation marker on purpose. Every pipeline
        # prompt instructs the model to cite, and a stand-in that ignores that
        # instruction is a bad double: `NaiveRagPipeline` correctly withholds an
        # uncited answer, so an uncited default would make every grounded-answer
        # test fail for a reason that has nothing to do with the code under test.
        self._responses = list(responses or _DEFAULT_RESPONSES)
        # What to answer a rewrite request with. `None` echoes the question, which is
        # what the Rewriter's own prompt asks for when a question already stands
        # alone. Set it to exercise a *specific* rewrite.
        self._rewrite = rewrite
        self._tool_calls = [list(t) for t in (tool_calls or [])]
        self._fail_after = fail_after
        self._latency_ms = latency_ms
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens

        # The observable record every test asserts against.
        self.call_count = 0
        # Rewrite calls, counted apart so a test can assert the stage ran without
        # the number colliding with the script's position.
        self.rewrite_count = 0
        self._scripted_calls = 0
        self.calls: list[list[Message]] = []
        # The tool names offered on each call, in order. What a caller *may* do is as
        # much a part of the contract as what it did — the web-search toggle turns on
        # the model not being told a tool exists, and that is only assertable here.
        self.tools_offered: list[list[str]] = []

    @traced(StepType.GENERATE, label="fake.complete")
    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
        tools: Sequence[ToolSpec] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Completion:
        self.call_count += 1
        self.calls.append(list(messages))
        self.tools_offered.append([spec.name for spec in (tools or [])])

        if self._fail_after is not None and self.call_count > self._fail_after:
            raise ProviderError(
                f"Fake provider failing deliberately on call {self.call_count}."
            )
        if self._latency_ms:
            await asyncio.sleep(self._latency_ms / 1000)

        # **A rewrite request gets a query back, not prose.**
        #
        # System Design Section 14 records the rule this follows, learned at
        # Milestone 0: *a test double must satisfy the contract it stands in for.* A
        # fake embedder that scored 0.75 for any pair of texts made a relevance
        # threshold meaningless; a fake LLM that ignored the instruction to cite made
        # every grounded-answer test fail. This is the same failure one stage earlier
        # and it is worse, because the Rewriter's output becomes the question every
        # later stage works on — so a canned "This is a fake answer [1]." was not
        # merely unhelpful, it replaced the student's question with itself and the
        # whole agentic pipeline then searched for that.
        #
        # Echoing the question is not a special case invented for the tests: it is
        # what the prompt's own rule 5 asks for ("if the question already stands
        # alone, reply with it unchanged") and what a real model does on most
        # questions.
        #
        # **It answers ahead of `responses`, and does not consume one.** A test
        # scripting `[route, decompose, answer]` wrote that list knowing which calls
        # the pipeline made, and a stage added in front of them should not silently
        # renumber it — the rewrite is not the call those tests are about. Handling
        # it here keeps the new stage transparent to every script that predates it.
        # A test that wants a *specific* rewrite passes `rewrite=`.
        if _asks_for_a_rewrite(messages):
            self.rewrite_count += 1
            reply = self._rewrite or _last_question(messages)
            return self._completion(reply, model=model)

        # Counted separately from `call_count`, which stays the honest total of every
        # LLM call this provider made — several tests prove "no call happened" by
        # asserting it is zero, and a rewrite *is* a paid call. This index is only
        # about position in the script.
        self._scripted_calls += 1
        index = min(self._scripted_calls - 1, len(self._responses) - 1)
        text = self._responses[index]
        calls: list[ToolCall] = (
            self._tool_calls[self._scripted_calls - 1]
            if self._scripted_calls - 1 < len(self._tool_calls)
            else []
        )
        return self._completion(text, model=model, calls=calls)

    def _completion(
        self,
        text: str,
        *,
        model: str | None,
        calls: list[ToolCall] | None = None,
    ) -> Completion:
        target = model or self.model
        calls = calls or []
        return Completion(
            text=text,
            model=target,
            usage=Usage(
                prompt_tokens=self._prompt_tokens,
                completion_tokens=self._completion_tokens,
                cost_usd=pricing.cost_of(
                    model=target,
                    prompt_tokens=self._prompt_tokens,
                    completion_tokens=self._completion_tokens,
                ),
            ),
            finish_reason=FinishReason.TOOL_CALLS if calls else FinishReason.STOP,
            tool_calls=calls,
        )

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[CompletionChunk]:
        completion = await self.complete(
            messages, model=model, max_tokens=max_tokens, temperature=temperature
        )
        # Word-by-word, so a test can observe more than one chunk and verify the
        # SSE plumbing genuinely streams rather than buffering to the end.
        words = completion.text.split()
        for word in words[:-1]:
            yield CompletionChunk(text=word + " ")
        if words:
            yield CompletionChunk(
                text=words[-1],
                usage=completion.usage,
                finish_reason=completion.finish_reason,
            )

    def estimate_cost(
        self,
        *,
        prompt_tokens: int,
        max_completion_tokens: int,
        model: str | None = None,
    ) -> Decimal:
        return pricing.cost_of(
            model=model or self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=max_completion_tokens,
        )

    def count_tokens(self, text: str) -> int:
        return pricing.estimate_tokens(text)


class FakeEmbeddingProvider:
    """Deterministic embeddings with real lexical behaviour.

    A **hashed bag of words**, not a hash of the whole string. The distinction
    matters more than it sounds, and an earlier version got it wrong in a way
    worth recording.

    Hashing the text into byte values divided by 255 gives vectors whose every
    component is positive. The cosine similarity of any two such vectors is
    around 0.75 regardless of content, so *nothing* ever falls below a relevance
    threshold — every query retrieves something, the "no sufficiently relevant
    content found" path can never fire, and a test asserting that path is
    untestable. The stub was not merely imprecise; it made a required behaviour
    unreachable.

    Hashing *tokens* into dimensions and counting them fixes it, because cosine
    similarity then measures word overlap:

        "How long is parental leave?" vs "Parental leave is 16 weeks"  → high
        "quantum cryptography policy" vs "a history of alpine cheese"  → ~0

    That is not semantic — no synonyms, no paraphrase — but it is enough for
    retrieval tests to assert the right chunk came back and the wrong one did
    not, deterministically and with no model. Where a test needs true semantic
    behaviour, that belongs in an evaluation run against a real provider, not in
    the offline suite.
    """

    name = "fake"

    def __init__(
        self,
        *,
        model: str = FAKE_EMBEDDING_MODEL,
        # Wide enough that hash collisions between unrelated tokens stay rare. At
        # 256 dimensions a 25-token passage collided often enough to score 0.25
        # against a completely unrelated query — which sits right on the default
        # relevance threshold and made "irrelevant" indistinguishable from
        # "marginally relevant" by luck of the hash.
        dimensions: int = 4096,
        latency_ms: int = 0,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self._latency_ms = latency_ms
        self.call_count = 0
        self.embedded_texts: list[str] = []

    @traced(
        StepType.EMBED,
        label="fake.embed",
        capture_output=False,
        attributes_from=embedding_attributes,
    )
    async def embed(
        self, texts: Sequence[str], *, model: str | None = None
    ) -> EmbeddingResult:
        self.call_count += 1
        self.embedded_texts.extend(texts)
        if self._latency_ms:
            await asyncio.sleep(self._latency_ms / 1000)

        target = model or self.model
        tokens = sum(pricing.estimate_tokens(t) for t in texts)
        return EmbeddingResult(
            vectors=[self._vector(t) for t in texts],
            model=target,
            usage=Usage(
                prompt_tokens=tokens,
                cost_usd=pricing.cost_of(model=target, prompt_tokens=tokens),
            ),
        )

    def _vector(self, text: str) -> list[float]:
        """A hashed, L2-normalised bag of words. See the class docstring."""
        vector = [0.0] * self.dimensions
        # The same tokenizer BM25 uses, so the fake's similarity tracks the
        # lexical relevance the keyword arm measures. See ai_backend/textutil.py.
        for token in tokenize(text):
            # A stable hash: Python's `hash()` is salted per process, which would
            # make embeddings differ between runs and quietly destroy the
            # determinism the whole suite relies on.
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            # Sign from a separate digest byte, so vectors are not all-positive
            # and unrelated text scores near zero rather than near 0.75.
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        magnitude = math.sqrt(sum(v * v for v in vector))
        if magnitude == 0:
            # Empty or punctuation-only text. A zero vector is correct — it is
            # similar to nothing, including itself.
            return vector
        return [v / magnitude for v in vector]

    def estimate_cost(self, *, prompt_tokens: int, model: str | None = None) -> Decimal:
        return pricing.cost_of(model=model or self.model, prompt_tokens=prompt_tokens)

    def count_tokens(self, text: str) -> int:
        return pricing.estimate_tokens(text)


class FakeVisionProvider:
    """Deterministic image captioning, derived from the image bytes.

    The caption is content-derived rather than constant, so two different images
    caption differently and an ingestion test can assert that the right image's
    text ended up in the right chunk — the same reasoning as
    `FakeEmbeddingProvider`.

    `captioned` records what it was asked to describe, which is how a test proves
    an image was actually routed through captioning rather than silently skipped.
    """

    name = "fake"

    def __init__(
        self,
        *,
        model: str = FAKE_LLM_MODEL,
        captions: Sequence[str] | None = None,
        fail_after: int | None = None,
        prompt_tokens: int = 250,
        completion_tokens: int = 40,
    ) -> None:
        self.model = model
        self._captions = list(captions or [])
        self._fail_after = fail_after
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens

        self.call_count = 0
        self.captioned: list[tuple[int, str]] = []

    @traced(StepType.INGEST, label="fake.caption_image", capture_input=False)
    async def caption_image(
        self, image: bytes, *, mime_type: str, prompt: str | None = None
    ) -> Caption:
        self.call_count += 1
        self.captioned.append((len(image), mime_type))

        if self._fail_after is not None and self.call_count > self._fail_after:
            raise ProviderError(
                f"Fake vision provider failing deliberately on call {self.call_count}."
            )

        if self._captions:
            text = self._captions[min(self.call_count - 1, len(self._captions) - 1)]
        else:
            # Stable per distinct image, and stated in words a retrieval test can
            # search for.
            digest = hashlib.sha256(image).hexdigest()[:8]
            text = (
                f"A diagram labelled {digest}. It shows two connected boxes "
                f"annotated with the value 42."
            )

        return Caption(
            text=text,
            model=self.model,
            usage=Usage(
                prompt_tokens=self._prompt_tokens,
                completion_tokens=self._completion_tokens,
                cost_usd=pricing.cost_of(
                    model=self.model,
                    prompt_tokens=self._prompt_tokens,
                    completion_tokens=self._completion_tokens,
                ),
            ),
        )


class FakeSearchProvider:
    """A canned web-search tool for exercising the agent's tool path.

    `call_count` is the assertion the search cap's test needs: proving "no search was
    made" requires an observable that counts calls, which a response body cannot be.

    Priced non-zero via `SEARCH_PRICES["fake"]`, for the same reason `fake-model` is:
    a search cap whose calls cost nothing could not be shown to bound anything.
    """

    name = "fake"

    def __init__(self, *, results: Sequence[dict[str, str]] | None = None) -> None:
        self._results = [
            WebSource(**entry)
            for entry in (
                results
                or [
                    {
                        "title": "Fake result",
                        "url": "https://example.test/1",
                        "snippet": "A fake web snippet about the question.",
                    }
                ]
            )
        ]
        self.call_count = 0
        self.queries: list[str] = []

    def estimate_cost(self) -> Decimal:
        return pricing.search_cost_of(self.name)

    @traced(StepType.SEARCH_WEB, label="fake.search")
    async def search(self, query: str, *, max_results: int = 5) -> SearchResult:
        self.call_count += 1
        self.queries.append(query)
        return SearchResult(
            sources=self._results[:max_results],
            usage=Usage(cost_usd=pricing.search_cost_of(self.name)),
        )


