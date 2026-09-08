"""`TraceStep` — the wire format the live canvas reads.

`AgentStep` is the internal shape; this is what crosses to the browser, over both
the snapshot endpoint and SSE. The two fields tested here were missing until
Milestone 2, and their absence is what made a streaming client impossible to write
rather than merely awkward.
"""

from __future__ import annotations

from decimal import Decimal

from ai_backend.contracts.models import AgentStep, StepType, Strategy, Usage
from backend.schemas.trace import TraceStep


def _step(**kwargs) -> AgentStep:
    return AgentStep(
        session_id=kwargs.pop("session_id", "s1"),
        trace_id=kwargs.pop("trace_id", "t1"),
        step_type=kwargs.pop("step_type", StepType.RETRIEVE),
        **kwargs,
    )


def test_seq_survives_the_conversion() -> None:
    """Without it, a streaming client cannot order a trace at all.

    A step is written when it *completes*, so over SSE a parent arrives after its own
    children — a canvas sorting by arrival renders a retrieval above the iteration
    that caused it. The snapshot endpoint sorts server-side, which is why the static
    pipeline strip never needed this and its absence went unnoticed.
    """
    step = _step()

    wire = TraceStep.from_agent_step(step)

    assert wire.seq == step.seq
    assert wire.seq > 0, "a real step always has a sequence number"


def test_trace_id_survives_the_conversion() -> None:
    """Which run a step belongs to.

    The SSE stream is scoped to a *session*, which accumulates every question. A
    client watching it needs to tell this run's steps from the previous one's.
    """
    step = _step(trace_id="run-42")

    assert TraceStep.from_agent_step(step).trace_id == "run-42"


def test_the_wire_format_carries_everything_a_canvas_needs() -> None:
    """One assertion over the whole payload, since it is a contract.

    `axis.js` reads `step_type`, `status`, `duration_ms`, `cost_usd`, `seq` and
    `attributes` by name. Renaming any of them silently breaks the canvas — nothing
    on the Python side would notice, because the consumer is a JavaScript file.
    """
    step = _step(
        step_type=StepType.SYNTHESIZE,
        strategy=Strategy.AGENTIC_RAG,
        label="AgenticRagPipeline.synthesize",
        duration_ms=1568,
        usage=Usage(prompt_tokens=559, completion_tokens=143, cost_usd=Decimal("0.000162")),
        attributes={"sub_questions": 4, "citations": 2},
    )

    payload = TraceStep.from_agent_step(step).model_dump(mode="json")

    for field in (
        "id",
        "seq",
        "trace_id",
        "step_type",
        "status",
        "label",
        "parent_step_id",
        "strategy",
        "duration_ms",
        "cost_usd",
        "attributes",
    ):
        assert field in payload, f"{field!r} is read by axis.js and must be on the wire"

    # Cost crosses as a float because JSON has no decimal, and the canvas only ever
    # displays it. The *ledger* uses `Answer.usage.cost_usd`, which stays a Decimal.
    assert isinstance(payload["cost_usd"], float)
    assert payload["attributes"]["sub_questions"] == 4, (
        "the canvas fans out its retrieve nodes from this value"
    )


def test_internal_fields_do_not_cross() -> None:
    """The wire format is narrower than `AgentStep` on purpose.

    `session_id` is the one that matters: it is the key the whole session's data is
    scoped by, and a client that has it in hand has no use for it beyond what the
    cookie already establishes.
    """
    payload = TraceStep.from_agent_step(_step()).model_dump(mode="json")

    assert "session_id" not in payload
    assert "usage" not in payload, "usage is flattened into plain numbers for templates"
