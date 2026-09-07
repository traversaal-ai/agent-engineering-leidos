"""Trace step as the Frontend sees it.

A separate shape from `AgentStep` rather than reusing it directly, and the
difference is the point: `narration` is present, `usage` is flattened into plain
numbers a template can render, and nothing internal leaks. The Frontend renders
this over SSE, so the field names here are effectively the wire format for the
live trace view.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ai_backend.contracts.models import AgentStep


class TraceStep(BaseModel):
    id: str
    # Creation order. The live canvas needs this and cannot work without it: a step is
    # *written* when it completes, so over SSE a parent always arrives after its own
    # children. Sorting by arrival renders a retrieval above the iteration that caused
    # it. The snapshot endpoint sorts server-side, which is why the static pipeline
    # strip never needed it — a streaming client does.
    seq: int = 0
    # Which run this step belongs to. Without it a client watching one session cannot
    # tell a step of the current question from a step of the previous one.
    trace_id: str = ""
    step_type: str
    status: str
    label: str = ""
    parent_step_id: str | None = None
    strategy: str | None = None
    raw_input: str | None = None
    raw_output: str | None = None
    # Null until a student first switches this step to the narrated view. Filled
    # by POST .../narrate and then cached, so toggling back and forth costs
    # nothing after the first time.
    narration: str | None = None
    started_at: datetime
    duration_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None
    attributes: dict[str, object] = Field(default_factory=dict)

    @classmethod
    def from_agent_step(cls, step: AgentStep) -> TraceStep:
        return cls(
            id=step.id,
            seq=step.seq,
            trace_id=step.trace_id,
            step_type=str(step.step_type),
            status=str(step.status),
            label=step.label,
            parent_step_id=step.parent_step_id,
            strategy=str(step.strategy) if step.strategy else None,
            raw_input=step.raw_input,
            raw_output=step.raw_output,
            narration=step.narration,
            started_at=step.started_at,
            duration_ms=step.duration_ms,
            prompt_tokens=step.usage.prompt_tokens,
            completion_tokens=step.usage.completion_tokens,
            cost_usd=float(step.usage.cost_usd),
            error=step.error,
            attributes=step.attributes,
        )


class NarrateResponse(BaseModel):
    step_id: str
    narration: str
    # False when the narration came from cache. Surfaced because PRD Section 6's
    # criterion is specifically that a second toggle makes no new LLM call — this
    # flag is what lets the acceptance test observe that.
    generated: bool
