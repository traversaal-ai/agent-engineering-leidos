"""Summarizer mode, on the wire.

`documents` is reported rather than left to be counted from `citations`, because the
two can legitimately differ: `MAX_DOCUMENTS` in `ai_backend/summarize.py` bounds how
many are read, and a student whose session held more needs to know the overview is
partial rather than infer it from a citation count they have no baseline for.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ai_backend.contracts.pipeline import DEFAULT_CORPUS
from backend.schemas.query import CitationOut


class SummarizeRequest(BaseModel):
    """Which documents to read. Optional, and `None` is not the same as empty.

    `None` — no body at all — means every indexed document, which is what this endpoint
    did before the Summarize page offered a choice, and what the evaluation harness and
    the API's own docs still mean by a bare POST.

    `[]` means the student unchecked everything, and is refused rather than treated as
    "all": summarization is the most expensive action Axis offers and its cost scales
    with the upload, so the reading that spends the most money is the wrong default for
    a request that named no documents.

    Bounded at 50 because a session holds five (PRD Section 6). Ids are only ever
    matched against what this session's own store returns, so an unknown or borrowed id
    selects nothing — the bound is against an oversized body, not against forgery.
    """

    document_ids: list[str] | None = Field(default=None, max_length=50)
    # Which corpus to read. `None` means every document *in this corpus* — the reading
    # that keeps the page's cost curve honest, since summarizing is meant to scale with
    # the corpus and a figure covering documents the student is not looking at is not
    # the figure the lesson claims.
    corpus: str = DEFAULT_CORPUS


class SummaryResponse(BaseModel):
    summary: str
    # How many documents the overview actually covers.
    documents: int = 0
    citations: list[CitationOut] = Field(default_factory=list)
    cost_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
