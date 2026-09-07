"""Provider interfaces — the seam that keeps pipelines provider-agnostic.

These are `Protocol`s rather than abstract base classes on purpose. A student
reading this module (PRD Section 4, post-class reference use) can write a
conforming provider without importing or inheriting from Axis at all; structural
typing means "has these methods" is the whole contract.

Async throughout, for one concrete reason: Compare mode has to run both strategies
concurrently to stay under the 45-second target in PRD Section 2, and an agentic run
makes several provider calls per query.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from decimal import Decimal
from typing import Protocol, runtime_checkable

from ai_backend.contracts.models import (
    Caption,
    Completion,
    CompletionChunk,
    EmbeddingResult,
    Message,
    SearchResult,
    ToolSpec,
)


@runtime_checkable
class LLMProvider(Protocol):
    """A chat-completion provider.

    Implementations live in `ai_backend/providers/`. They are responsible for
    translating to and from their vendor's wire format — including the tool
    calling shape — so that nothing downstream of this interface knows which
    vendor is configured.
    """

    name: str
    model: str

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
        tools: Sequence[ToolSpec] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Completion: ...

    def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[CompletionChunk]: ...

    def estimate_cost(
        self,
        *,
        prompt_tokens: int,
        max_completion_tokens: int,
        model: str | None = None,
    ) -> Decimal:
        """Upper-bound cost of a call that has not been made yet.

        This is the load-bearing method of the whole interface. PRD Section 6
        requires a session's cost cap be enforced *before* any LLM call, and that
        is impossible using only the usage figures a vendor returns afterwards.
        So the estimate is part of the contract, not a convenience: assume the
        completion runs to `max_completion_tokens` and price it.
        """
        ...

    def count_tokens(self, text: str) -> int:
        """Token count used for the pre-call estimate.

        Implementations may approximate. An approximation that errs high is
        correct behaviour here — it makes the cap trip early rather than late.
        """
        ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """An embedding provider.

    Note there is no Anthropic implementation: Anthropic publishes no embeddings
    API. `ai_backend/providers/registry.py` rejects that configuration at startup
    with an explanatory message rather than failing at the first query.
    """

    name: str
    model: str
    dimensions: int

    async def embed(
        self,
        texts: Sequence[str],
        *,
        model: str | None = None,
    ) -> EmbeddingResult: ...

    def estimate_cost(
        self,
        *,
        prompt_tokens: int,
        model: str | None = None,
    ) -> Decimal: ...

    def count_tokens(self, text: str) -> int: ...


@runtime_checkable
class VisionProvider(Protocol):
    """Turns an image into a text caption.

    Deliberately one narrow method rather than general multimodal chat. System
    Design Section 10 chose to *caption* images and embed the caption as text,
    rather than use native multimodal embeddings — cheaper and simpler, at the
    cost of fidelity. Expressing that as its own interface keeps the trade-off
    visible: nothing in Axis can accidentally start doing native multimodal
    retrieval, because no interface offers it.

    The alternative — widening `Message.content` to carry image blocks — would
    push a multimodal shape into every provider adapter and into Milestone 1's
    ReAct loop, which never needs one. Captioning happens once, at ingestion.
    """

    name: str
    model: str

    async def caption_image(
        self,
        image: bytes,
        *,
        mime_type: str,
        prompt: str | None = None,
    ) -> Caption:
        """Describe an image as text suitable for embedding.

        `prompt` steers the caption toward what retrieval needs — the numbers in
        a chart, the boxes and arrows in a diagram — rather than an aesthetic
        description. A caption that says "a bar chart" is useless to a student
        asking what the chart shows.
        """
        ...


@runtime_checkable
class SearchProvider(Protocol):
    """The agent's only route to the public internet.

    Deliberately a narrow search interface rather than a general URL fetch —
    that is the SSRF control in System Design Section 6.5, expressed as an
    interface boundary instead of a validation rule that could be forgotten.
    **There is no `fetch`, and adding one would be a security change, not a
    feature.** A result's `url` is something to show a student, never something
    Axis requests.

    `search` returns a `SearchResult` rather than a bare list so the call's cost
    travels with its output, exactly as `Completion` and `EmbeddingResult` do. A
    provider that returned only results would leave the caller to look the price up,
    and the one caller that forgot would silently make web search free.
    """

    name: str

    async def search(self, query: str, *, max_results: int = 5) -> SearchResult: ...

    def estimate_cost(self) -> Decimal:
        """Cost of one call, before making it.

        Separate from the cost reported afterwards because the per-session cap must
        be checked *before* the request (CLAUDE.md). For a flat-rate API the two
        numbers are the same, which is a property of search pricing rather than
        something callers may assume.
        """
        ...
