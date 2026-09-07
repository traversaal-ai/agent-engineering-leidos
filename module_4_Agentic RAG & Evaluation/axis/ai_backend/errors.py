"""AI Backend exception hierarchy.

Each class maps to a row of System Design Section 11's failure-mode table. They
exist as distinct types rather than one generic error because the requirement is
that failures be *distinguishable* in the trace and the UI: "the agent ran out of
budget" and "nothing relevant was retrieved" are different lessons, and a
student staring at a red box learns nothing from either if both say "Error".

`backend/core/errors.py` maps these to HTTP responses. Nothing here knows about
HTTP — that translation is the Backend's job.
"""

from __future__ import annotations


class AxisError(Exception):
    """Base for every error Axis raises deliberately.

    `message` is safe to show a student. Anything sensitive belongs in the log,
    never in this string — it travels to the Frontend.
    """

    code = "axis_error"

    # Whether this is a *designed* refusal rather than a fault. Expected errors
    # are logged as a single line; unexpected ones get a full stack trace.
    #
    # The distinction earns its keep in a workshop: "your provider cannot call tools,
    # so the agentic strategy is unavailable" is a designed refusal with a stated fix,
    # and tracebacking it would bury the real faults in a session's logs under noise
    # that means nothing is wrong.
    is_expected = False

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class ConfigurationError(AxisError):
    """Raised at startup, never mid-request.

    Fail-fast is the point: a missing key discovered when the instructor types
    the first question in front of a class is a much worse outcome than a
    refusal to boot.
    """

    code = "configuration_error"


class ProviderError(AxisError):
    """An external LLM/embedding/search call failed."""

    code = "provider_error"


class ProviderRateLimitError(ProviderError):
    """The vendor throttled us.

    Its own type because PRD Section 7 flags a whole classroom hitting one
    provider simultaneously as a live risk, and it warrants a different message
    to the student than a generic provider fault.
    """

    code = "provider_rate_limited"
    is_expected = True


class UnknownModelError(ConfigurationError):
    """A model with no entry in the pricing table was requested.

    This is fatal by design. If an unpriced model were allowed through, its cost
    would be counted as zero and the per-session cap — the single most important
    control in the system — would silently become unlimited.
    """

    code = "unknown_model"


class BudgetExceededError(AxisError):
    """A cap was reached. Raised *before* the call it would have paid for."""

    code = "budget_exceeded"
    is_expected = True


class RetrievalUnavailableError(AxisError):
    """A retriever has no usable index for this session.

    Distinct from a retrieval that simply found nothing, which is a legitimate outcome
    and must not raise. This is "there is no index for this session at all" — nothing
    has been uploaded, or indexing failed — and conflating the two would tell a student
    their documents do not answer a question they never uploaded (System Design
    Section 11).
    """

    code = "retrieval_unavailable"
    is_expected = True


class IngestionError(AxisError):
    """A document could not be parsed or indexed."""

    code = "ingestion_error"
    is_expected = True


class UnsupportedStrategyError(AxisError):
    """A strategy was requested that is not registered, or cannot run as configured.

    Both strategies are built, so in practice this is the configuration case: an LLM
    provider whose adapter cannot call tools leaves Agentic RAG `mark_unavailable`, with
    a reason naming the variable to change. An *unknown* strategy name never reaches
    here — Pydantic rejects it at the request boundary as a 400.
    """

    code = "unsupported_strategy"
    is_expected = True
