"""Search providers — the agent's only route to the public internet.

Three implementations, and the middle one is the interesting decision.

**`SerpApiSearchProvider`** mirrors the reference notebook
(`reference/chapter_07_enterprise_rag/agentic_router.py`), including its
answer-box-then-organic-results parsing, so a student who read the notebook
recognises the shape.

**`CachedSearchProvider`** replays recorded results from disk. PRD Section 5 requires
the demo run on a single machine without depending on fragile network infrastructure,
and a live search API in front of a class is exactly that dependency. The reference
notebook is the cautionary example rather than a hypothetical: its two internet cells
show `404 Client Error ... api-ares.traversaal.ai` in committed output, having been
migrated to a new provider and never successfully re-run. Beyond availability, live
results *change* — an instructor cannot rehearse a demo whose answer differs between
the rehearsal and the room.

**`FakeSearchProvider`** lives in `fake.py` with the other test doubles.

None of the three fetches a URL. That is the SSRF control in System Design Section
6.5, and it is expressed here as an absence: there is no method that takes an
address. A result's `url` is shown to the student and never requested by Axis.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from ai_backend.contracts.models import SearchResult, StepType, Usage, WebSource
from ai_backend.errors import ConfigurationError, ProviderError, ProviderRateLimitError
from ai_backend.observability.trace import traced
from ai_backend.providers import pricing

SERPAPI_URL = "https://serpapi.com/search.json"

# Where `CachedSearchProvider` reads from. Committed JSON rather than a binary
# cache, so a diff shows exactly what the class will see — the same reasoning that
# keeps the golden fixtures as readable Markdown.
CACHE_DIR = Path(__file__).resolve().parents[1] / "evaluation" / "search_cache"


def _usage_for(provider: str) -> Usage:
    """One search call's usage. Tokens are zero; the cost is the flat rate."""
    return Usage(
        prompt_tokens=0,
        completion_tokens=0,
        cost_usd=pricing.search_cost_of(provider),
    )


class SerpApiSearchProvider:
    """Live Google results via SerpApi."""

    name = "serpapi"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            # Refused at construction rather than at first use. A search provider
            # that raised only when the agent finally routed to the web would fail
            # mid-demo, on the one query the instructor chose to show it off.
            raise ConfigurationError(
                "AXIS_SEARCH__PROVIDER=serpapi needs AXIS_SEARCH__API_KEY.",
                detail=(
                    "Set the key, or use 'cached' for a rehearsable demo and 'none' "
                    "to disable the web route entirely."
                ),
            )
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._transport = transport

    def estimate_cost(self) -> Decimal:
        return pricing.search_cost_of(self.name)

    @traced(StepType.SEARCH_WEB, label="serpapi.search")
    async def search(self, query: str, *, max_results: int = 5) -> SearchResult:
        params = {
            "q": query,
            "api_key": self._api_key,
            "engine": "google",
            "num": max_results,
        }

        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            try:
                response = await client.get(SERPAPI_URL, params=params)
            except httpx.TimeoutException as exc:
                raise ProviderError(
                    f"The search provider did not respond within "
                    f"{self._timeout:.0f}s.",
                    detail=str(exc),
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(
                    "Could not reach the search provider.", detail=str(exc)
                ) from exc

        if response.status_code == 429:
            raise ProviderRateLimitError(
                "The search provider is rate limiting requests. Wait a moment and "
                "try again.",
            )
        if response.status_code >= 400:
            # No response body in the detail. A SerpApi error echoes the request,
            # and the request contains the API key — this is the one place where the
            # usual "include the body, redaction will catch it" habit is the wrong
            # trade, because the key is a *query parameter* rather than a header and
            # redaction keys on header-shaped patterns.
            raise ProviderError(
                f"The search provider returned HTTP {response.status_code}."
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderError(
                "The search provider returned a response that was not JSON."
            ) from exc

        return SearchResult(
            sources=_parse_serpapi(body, max_results=max_results),
            # Charged whether or not anything was found. A search that returns
            # nothing still cost a call, and reporting it as free would understate
            # the web route in exactly the case it performed worst.
            usage=_usage_for(self.name),
        )


class CachedSearchProvider:
    """Replays recorded results. The class-demo provider.

    Deterministic and offline. A query with no recording returns nothing rather than
    falling through to a live call: a silent fallback would make the demo
    network-dependent again at exactly the moment nobody was watching for it, and
    "no results" is a state the pipeline already handles visibly.
    """

    name = "cached"

    def __init__(self, *, cache_dir: Path | None = None) -> None:
        self._dir = cache_dir or CACHE_DIR
        self._entries = _load_cache(self._dir)
        if not self._entries:
            # Refused at construction, loudly, during prep. A cached provider with no
            # recordings would return nothing for every query — so the web route
            # would appear configured, the router would route to it, and every search
            # would come back empty *in the room*. That is precisely the failure this
            # provider exists to prevent, so it must not be reachable by
            # misconfiguration.
            raise ConfigurationError(
                f"AXIS_SEARCH__PROVIDER=cached, but no search recordings were found "
                f"in {self._dir}.",
                detail=(
                    "Record the demo queries first (see the README in that "
                    "directory), or use 'serpapi' for live search and 'none' to "
                    "disable the web route."
                ),
            )

    def estimate_cost(self) -> Decimal:
        return pricing.search_cost_of(self.name)

    @traced(StepType.SEARCH_WEB, label="cached.search")
    async def search(self, query: str, *, max_results: int = 5) -> SearchResult:
        recorded = self._entries.get(_cache_key(query))
        return SearchResult(
            sources=[WebSource(**entry) for entry in (recorded or [])][:max_results],
            usage=_usage_for(self.name),
        )

    @property
    def recorded_queries(self) -> list[str]:
        """Which queries have recordings, for a startup check or a demo script."""
        return sorted(self._entries)


def _cache_key(query: str) -> str:
    """Whitespace- and case-insensitive, so a retyped question still hits.

    Not a hash: the cache file is meant to be read and edited by a human preparing a
    demo, and a file keyed by hex digests could not be.
    """
    return " ".join(query.lower().split())


def _load_cache(directory: Path) -> dict[str, list[dict[str, str]]]:
    """Every `*.json` in the cache directory, merged.

    One file per topic rather than one big file, so adding a demo query is a new file
    rather than a merge conflict. A malformed file is fatal: a demo that silently
    lost half its recordings would fail in the room, which is the failure this
    provider exists to prevent.
    """
    if not directory.is_dir():
        return {}

    merged: dict[str, list[dict[str, str]]] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ConfigurationError(
                f"The search cache file {path.name} is not valid JSON.",
                detail=str(exc),
            ) from exc
        if not isinstance(raw, dict):
            raise ConfigurationError(
                f"The search cache file {path.name} must be a JSON object mapping "
                f"a query to its results."
            )
        for query, results in raw.items():
            merged[_cache_key(str(query))] = list(results or [])
    return merged


def _parse_serpapi(body: dict[str, Any], *, max_results: int) -> list[WebSource]:
    """SerpApi's response, in the notebook's order of preference.

    The answer box first — Google's own extracted direct answer, and the single most
    useful thing in the response — then organic results. Matching the notebook here
    is deliberate: a student who read it should recognise what came back.
    """
    sources: list[WebSource] = []

    answer_box = body.get("answer_box") or {}
    direct = answer_box.get("answer") or answer_box.get("snippet")
    if direct:
        sources.append(
            WebSource(
                title=answer_box.get("title") or "Direct answer",
                url=answer_box.get("link") or "",
                snippet=str(direct),
            )
        )

    for result in (body.get("organic_results") or [])[:max_results]:
        snippet = result.get("snippet")
        if not snippet:
            # A result with no snippet is a title and a link. There is nothing to
            # ground an answer in, and passing it to synthesis would invite the
            # model to answer from the title alone.
            continue
        sources.append(
            WebSource(
                title=result.get("title") or "",
                url=result.get("link") or "",
                snippet=str(snippet),
            )
        )

    return sources[:max_results]


__all__ = ["CachedSearchProvider", "SerpApiSearchProvider"]
