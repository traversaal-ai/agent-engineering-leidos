"""Compare mode — one question, both strategies, side by side.

Note `StrategyResult.status`: PRD Section 6 requires that if one strategy fails,
"that strategy's column shows the failure, not a blank cell, and the other still
renders". A schema where `answer` were non-optional would make that impossible to
express, and the failure would have to be smuggled through as an error string in the
answer text.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ai_backend.contracts.models import Strategy
from ai_backend.contracts.pipeline import DEFAULT_CORPUS
from backend.schemas.query import CitationOut


class CompareRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    # Defaults to every strategy. Narrowing it to one is useful mid-course, to show
    # the baseline's behaviour before the orchestrated version has been explained.
    strategies: list[Strategy] | None = None
    # Which corpus every strategy searches. One value for the whole comparison, not
    # one per strategy: two strategies reading different corpora is not a comparison
    # of strategies.
    corpus: str = DEFAULT_CORPUS


class StrategyResult(BaseModel):
    strategy: Strategy
    status: str  # "ok" | "error" | "unavailable" | "budget_exceeded"
    answer: str | None = None
    trace_id: str | None = None
    citations: list[CitationOut] = Field(default_factory=list)
    latency_ms: int = 0
    cost_usd: float = 0.0
    # From the evaluation harness. Null when no golden answer exists for this
    # question — most student-authored questions — since a fabricated score would
    # be worse than an absent one.
    quality_score: float | None = None
    error: str | None = None


class CompareResponse(BaseModel):
    comparison_run_id: str
    question: str
    results: list[StrategyResult] = Field(default_factory=list)
    total_latency_ms: int = 0
    total_cost_usd: float = 0.0
