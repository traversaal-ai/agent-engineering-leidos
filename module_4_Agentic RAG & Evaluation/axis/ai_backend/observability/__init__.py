"""Axis's observability library — custom-built, no external framework.

The deliberate choice not to use Langfuse, LangSmith, or OpenTelemetry is
recorded in System Design Section 10 and enforced by CLAUDE.md. The reason is
pedagogical: this package is small enough to read in one sitting, so a student
can see exactly what a trace captures and why, instead of trusting a framework's
output.

Typical use:

    from ai_backend.observability import StepType, trace_context, traced

    @traced(StepType.RETRIEVE)
    async def retrieve(self, query: str, ...) -> RetrievedContext:
        ...

    with trace_context(session_id=sid, trace_id=tid, strategy=strategy):
        await pipeline.run(ctx)
"""

from ai_backend.contracts.models import AgentStep, StepStatus, StepType
from ai_backend.observability.context import TraceContext, child_of, current, trace_context
from ai_backend.observability.redact import redact_step, redact_text
from ai_backend.observability.store import (
    AgentStepStore,
    InMemoryStepStore,
    SqliteStepStore,
    aggregate_usage,
)
from ai_backend.observability.trace import (
    StepHandle,
    atrace_step,
    configure,
    get_store,
    trace_step,
    traced,
)

__all__ = [
    "AgentStep",
    "AgentStepStore",
    "InMemoryStepStore",
    "SqliteStepStore",
    "StepHandle",
    "StepStatus",
    "StepType",
    "TraceContext",
    "aggregate_usage",
    "atrace_step",
    "child_of",
    "configure",
    "current",
    "get_store",
    "redact_step",
    "redact_text",
    "trace_context",
    "trace_step",
    "traced",
]
