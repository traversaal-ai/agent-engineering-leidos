"""Session creation and inspection."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    """Optional overrides at session creation.

    An instructor can hand a demo session a smaller budget than the server
    default. Only *downward* — see the clamp in the sessions route. A request
    body that could raise its own cap would not be a cap.
    """

    label: str | None = Field(default=None, max_length=100)
    cap_cost_usd: float | None = Field(default=None, gt=0)
    cap_requests: int | None = Field(default=None, gt=0)


class SessionCreateResponse(BaseModel):
    session_id: str
    # Returned exactly once and never stored in plaintext — only its SHA-256
    # hash reaches the database.
    token: str
    expires_at: datetime
    cap_cost_usd: float
    cap_requests: int


class SessionInfo(BaseModel):
    """Current state of a session, including what is left of its budget.

    Surfaced to the Frontend so a student can see their remaining budget before
    they hit the cap, rather than discovering it through a refusal.
    """

    session_id: str
    created_at: datetime
    expires_at: datetime
    document_count: int
    request_count: int
    cap_requests: int
    spent_usd: float
    cap_cost_usd: float
    remaining_usd: float
    # Exchanges the *current* conversation can refer back to — not every question
    # this session has asked, which is what the Trace page lists. Reported here so
    # the sidebar's count and the history the rewriter actually receives come from
    # one place and cannot disagree; the alternative was counting runs in the
    # Frontend, which knows nothing about the conversation watermark.
    turn_count: int = 0
    # Documents per corpus — `{"demo": 5, "mine": 2}`, with a key present only once
    # that corpus holds something.
    #
    # Here rather than fetched separately because `_chrome()` renders the corpus rail
    # group on every page and already fetches this object for spend and turn count.
    # A second round trip per page render to count five rows would be the kind of cost
    # that arrives one call at a time.
    corpora: dict[str, int] = Field(default_factory=dict)
