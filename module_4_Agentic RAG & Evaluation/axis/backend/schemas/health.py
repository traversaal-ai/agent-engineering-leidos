"""Health check response.

Shaped by PRD Section 6's single-machine criterion, which asks that "all three
layers come up and pass the /api/v1/health check without any external service
beyond the configured LLM/embedding/search providers". So the response reports
each layer separately — a single `{"status": "ok"}` could not evidence that
claim.

Note what a shallow check deliberately does *not* do: call a provider. A slow
OpenAI must never make Axis look down thirty seconds before a class starts, and
liveness is a question about Axis, not about a vendor. `?deep=true` is there for
when you actually want to know whether the keys work.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LayerHealth(BaseModel):
    name: str
    status: str  # "ok" | "degraded" | "error"
    detail: str | None = None


class ProviderHealth(BaseModel):
    """Only populated for a deep check."""

    name: str
    kind: str  # "llm" | "embedding" | "search"
    model: str
    reachable: bool | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded" | "error"
    version: str
    # Reported so an instructor can confirm both strategies are live before a class,
    # rather than discovering a tool-incapable provider mid-demo.
    available_strategies: list[str] = Field(default_factory=list)
    layers: list[LayerHealth] = Field(default_factory=list)
    providers: list[ProviderHealth] = Field(default_factory=list)
    # True when configuration validated at startup. False means Axis is running
    # but would refuse queries — the distinction a bare 200 would hide.
    config_valid: bool = True
    config_error: str | None = None
    # Whether a web search provider is configured — the *capability*, so the Frontend
    # knows whether to offer the toggle at all. A switch that cannot enable anything is
    # worse than no switch: it invites "I turned it on, why is nothing happening?",
    # which is not a question the demo exists to answer.
    #
    # A boolean, not the provider's name. Which service an instructor pays for is not
    # something the browser needs, and `AXIS_SEARCH__API_KEY` lives next to it.
    web_search_available: bool = False
