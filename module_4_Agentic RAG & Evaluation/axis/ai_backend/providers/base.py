"""Shared machinery for HTTP-backed providers.

Why raw `httpx` instead of the official vendor SDKs:

- The engineering foundation installs and tests fully offline, with no SDK
  version churn to manage across a course that will be re-run over time.
- One `respx` mock covers all three adapters identically, so the conformance
  test in `tests/contract/` is genuinely the same suite for each.
- Students see the actual request and response shapes. "Swappable providers" is
  much more convincing when you can read the two dozen lines that make OpenAI
  and Anthropic interchangeable than when both are one import away.

The trade-off is real and worth naming in class: no automatic retry policies, no
vendor-maintained streaming parser, and new API features need hand-wiring.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import httpx

from ai_backend.contracts.models import Usage
from ai_backend.errors import ProviderError, ProviderRateLimitError
from ai_backend.providers import pricing

# Shared by every VisionProvider, so a PNG is described the same way whichever
# vendor is configured — otherwise switching providers would silently change what
# gets embedded, and the cross-strategy comparison would be measuring the caption
# style as much as the retrieval.
#
# The instruction is aggressively retrieval-oriented on purpose. A model's default
# caption ("a bar chart with blue bars") is useless to a student asking what the
# chart *says*; the numbers, labels, and relationships are the retrievable content.
CAPTION_PROMPT = (
    "Describe this image so it can be found later by a text search. "
    "Transcribe all visible text, labels, axis titles, legends, and numbers "
    "exactly. If it is a chart or table, state the values and what they measure. "
    "If it is a diagram, state each element and how they connect. "
    "Do not comment on style, colour, or composition. Be factual and complete."
)

# Enough for a dense diagram, bounded so one pathological image cannot dominate
# an ingestion bill.
CAPTION_MAX_TOKENS = 600


# ── Showing a student what an embedding is ────────────────────────────────────
#
# How many of a vector's numbers reach the trace. The full vector never does, and
# the reason is unchanged: 1,536 floats flood the view and teach nothing. But the
# *first few* are the single most useful thing this platform can show someone who
# has just been told that text becomes a vector — without them, "embedding" stays
# a word. So both facts are honoured: `capture_output=False` on the provider call,
# and these two slices on the step.
#
# HEAD is what a student reads aloud. STRIP is what gets drawn as a bar chart, so
# two vectors can be compared by shape at a glance.
VECTOR_HEAD = 8
VECTOR_STRIP = 48

# The strongest dimensions, by magnitude, with their positions.
#
# **Not decoration — without this the offline demo shows nothing.** The head is
# genuinely the first eight numbers, which is the honest thing to show and is
# legible for a dense vector from OpenAI or Ollama. `FakeEmbeddingProvider` is a
# hashed bag of words over 4,096 dimensions, so a 25-token chunk sets about 25 of
# them and the first eight are reliably `[0, 0, 0, 0, 0, 0, 0, 0]` — for every
# chunk, and for the query too. A class running offline would watch two different
# texts produce identical all-zero vectors and reasonably conclude the thing is
# broken.
#
# The fake's maths is not the problem to fix: its sparsity and its sign trick are
# what make its similarity track lexical relevance, which the golden set's
# thresholds are tuned against. So the display adapts instead. `notable` carries
# signal for a sparse vector and is independently interesting for a dense one —
# "which dimensions is this text strongest in" is a better question than "what are
# the first eight", it is just not the one to lead with.
VECTOR_NOTABLE = 6


def vector_preview(vector: Sequence[float]) -> dict[str, object]:
    """The readable part of one vector, for a trace attribute.

    Rounded to four decimals: a raw float renders as `0.021345891654491425`, which
    is nineteen characters of false precision and unreadable on a projector. Four
    is enough to see that two numbers differ and that some are negative, which is
    all the head is there to show.
    """
    values = [float(v) for v in vector]
    ranked = sorted(
        (i for i, v in enumerate(values) if v),
        key=lambda i: abs(values[i]),
        reverse=True,
    )[:VECTOR_NOTABLE]

    return {
        "dimensions": len(values),
        "vector_head": [round(v, 4) for v in values[:VECTOR_HEAD]],
        "vector_strip": [round(v, 4) for v in values[:VECTOR_STRIP]],
        # How many dimensions carry anything at all. Makes the dense/sparse
        # difference between a real provider and the offline stand-in visible
        # rather than something a student silently mis-generalises from.
        "nonzero": sum(1 for v in values if v),
        "notable": [{"i": i, "v": round(values[i], 4)} for i in sorted(ranked)],
    }


def embedding_attributes(result: object) -> dict[str, object]:
    """Trace attributes for an embedding call, for `traced(attributes_from=...)`.

    Reports what the *provider* did — how many vectors, of what width, from which
    model. What the vectors were *for* is not knowable here (a provider has no idea
    whether it is indexing a document or embedding a question), so the calling
    stage records that on its own step. Providers report what they did; stages
    report what it was for.
    """
    vectors = getattr(result, "vectors", None)
    if not vectors:
        return {}
    return {
        "model": getattr(result, "model", ""),
        "vectors": len(vectors),
        **vector_preview(vectors[0]),
    }


class HttpProvider:
    """Base for providers that talk to an HTTP endpoint."""

    name: str = "http"

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None,
        base_url: str,
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        # Injectable so tests can supply a mock transport. This is what lets the
        # real adapters be exercised with no network and no API key.
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    async def _post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            try:
                response = await client.post(url, json=payload, headers=self._headers())
            except httpx.TimeoutException as exc:
                raise ProviderError(
                    f"The {self.name} provider did not respond within "
                    f"{self._timeout:.0f}s.",
                    detail=str(exc),
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(
                    f"Could not reach the {self.name} provider.", detail=str(exc)
                ) from exc

        if response.status_code == 429:
            # Its own error type because PRD Section 7 flags a whole classroom
            # hitting one provider at once as a live risk, and the student-facing
            # message should say "busy", not "broken".
            raise ProviderRateLimitError(
                f"The {self.name} provider is rate limiting requests. Wait a "
                f"moment and try again.",
                detail=_safe_body(response),
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"The {self.name} provider returned HTTP {response.status_code}.",
                detail=_safe_body(response),
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderError(
                f"The {self.name} provider returned a response that was not JSON.",
                detail=_safe_body(response),
            ) from exc
        if not isinstance(body, dict):
            raise ProviderError(
                f"The {self.name} provider returned {type(body).__name__}, "
                f"expected a JSON object."
            )
        return body

    # -- cost -------------------------------------------------------------

    def count_tokens(self, text: str) -> int:
        return pricing.estimate_tokens(text)

    def _usage(self, *, prompt_tokens: int, completion_tokens: int, model: str) -> Usage:
        return Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=pricing.cost_of(
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            ),
        )

    def estimate_cost(
        self,
        *,
        prompt_tokens: int,
        max_completion_tokens: int,
        model: str | None = None,
    ) -> Decimal:
        """Upper bound on a call not yet made — see `LLMProvider.estimate_cost`.

        Prices the completion at its full permitted length. The estimate is
        therefore pessimistic, which is the only safe direction when the number
        is used to decide whether to spend a shared budget.
        """
        return pricing.cost_of(
            model=model or self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=max_completion_tokens,
        )


def _safe_body(response: httpx.Response) -> str:
    """A truncated response body for an error detail.

    Truncated because provider errors sometimes echo the request back, and a
    request can be large. Note the body still passes through trace redaction
    before it could ever reach a student — vendors do sometimes include a
    partially-masked key in an auth error.
    """
    try:
        return response.text[:500]
    except Exception:  # noqa: BLE001
        return "[unreadable response body]"
