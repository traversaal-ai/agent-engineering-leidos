"""`@traced` — the decorator every external call in Axis passes through.

Custom-built on purpose. CLAUDE.md rules out Langfuse, LangSmith, and
OpenTelemetry, and that is a teaching decision rather than an oversight: the
entire mechanism by which a trace comes into existence is about 150 readable
lines, so a student can open this file and see exactly what is captured, when,
and why. A framework would hide precisely the thing the course is trying to
teach.

Three behaviours are load-bearing:

1. **Errors are recorded, then re-raised.** System Design Section 11 requires
   failures be visible in the trace. Swallowing an exception here would make the
   trace lie, which is worse than no trace at all.
2. **Steps are emitted even on failure.** The step's duration and inputs are
   often the most instructive part of a failed call.
3. **Nesting is automatic.** The decorated function body runs inside
   `child_of(step_id)`, so anything it calls is recorded as a child without
   having to know it is being traced.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import logging
import time
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any, ParamSpec, TypeVar

from ai_backend.contracts.models import (
    AgentStep,
    StepStatus,
    StepType,
    Usage,
    new_id,
    utc_now,
)
from ai_backend.errors import BudgetExceededError
from ai_backend.observability import context as trace_ctx
from ai_backend.observability.store import AgentStepStore, InMemoryStepStore

logger = logging.getLogger("axis.trace")

P = ParamSpec("P")
R = TypeVar("R")

# The process-wide sink. Set once during application startup by
# `configure(store=...)`; defaults to an in-memory store so that importing the
# AI Backend in a notebook or a test never requires wiring anything up first.
_store: AgentStepStore = InMemoryStepStore()

# How much of an input/output payload is kept. The trace is shown to students and
# exported into reports, so an unbounded blob would make it unreadable and would
# quietly balloon the SQLite file across a workshop.
MAX_PAYLOAD_CHARS = 4_000


def configure(*, store: AgentStepStore) -> None:
    global _store
    _store = store


def get_store() -> AgentStepStore:
    return _store


def _truncate(text: str) -> str:
    if len(text) <= MAX_PAYLOAD_CHARS:
        return text
    omitted = len(text) - MAX_PAYLOAD_CHARS
    return f"{text[:MAX_PAYLOAD_CHARS]}… [{omitted} more characters omitted]"


def _render(value: Any) -> str | None:
    if value is None:
        return None
    try:
        text = value if isinstance(value, str) else repr(value)
    except Exception:  # noqa: BLE001 - a broken __repr__ must not break a trace
        return "[unrenderable value]"
    return _truncate(text)


def _usage_of(result: Any) -> Usage:
    """Pull `Usage` off a result if it has any.

    Providers return `Completion`/`EmbeddingResult`; retrievers return
    `RetrievedContext`. All three carry `.usage`, so cost lands on the step that
    incurred it without any per-call-site bookkeeping — which is what makes the
    two strategies comparable on cost by construction.
    """
    usage = getattr(result, "usage", None)
    return usage if isinstance(usage, Usage) else Usage()


def _status_for(exc: BaseException) -> StepStatus:
    # A cap being reached is a designed outcome, not a fault, and the UI renders
    # it differently ("stopped: budget reached" per Section 11).
    return StepStatus.BUDGET_EXCEEDED if isinstance(exc, BudgetExceededError) else StepStatus.ERROR


async def _emit(step: AgentStep) -> None:
    """Persist a step, never letting the attempt break the traced call.

    A failure to record an observation must not fail the operation being
    observed. During a live demo a broken store should cost you the trace pane,
    not the answer on screen.
    """
    try:
        await _store.append(step)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to record AgentStep id=%s type=%s", step.id, step.step_type)


def _emit_soon(step: AgentStep) -> None:
    """Emit from synchronous code.

    Inside a running loop the write is scheduled; outside one it runs to
    completion. This is what lets `@traced` decorate sync helpers such as a
    chunker without forcing them to become async.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_emit(step))
        return
    task = loop.create_task(_emit(step))
    # Hold a reference so the task is not garbage-collected mid-flight.
    _pending.add(task)
    task.add_done_callback(_pending.discard)


_pending: set[asyncio.Task[None]] = set()


def _build_step(
    *,
    step_type: StepType,
    label: str,
    raw_input: str | None,
    attributes: dict[str, Any],
) -> AgentStep:
    """The step as it exists before its body has run: open, with no outcome yet.

    `status` is `RUNNING` here and every caller overwrites it on the way out. Both
    writes carry the same `id` and the same `seq`, which is what makes the second
    one an *update* rather than a second row — see `_open`.
    """
    ctx = trace_ctx.require()
    return AgentStep(
        id=new_id(),
        session_id=ctx.session_id,
        trace_id=ctx.trace_id,
        parent_step_id=ctx.parent_step_id,
        strategy=ctx.strategy,
        step_type=step_type,
        status=StepStatus.RUNNING,
        label=label,
        raw_input=raw_input,
        started_at=utc_now(),
        attributes=attributes,
    )


# The stages the canvas draws as cards, and the only ones a teaching pause applies
# to.
#
# Not every traced call, and the distinction is the reason this list can be short:
# `@traced` wraps one external call, while `atrace_step` marks a region somebody
# placed by hand because it is a phase of RAG worth naming. Pausing on the second
# gives exactly one pause per card. Pausing on the first would multiply the delay by
# the nesting depth — a retrieval would pause, then its embedding call would pause
# again inside it — and would pace `ingest`, `iterate`, `call_tool`, `narrate` and
# `summarize`, none of which a student is watching for.
PACED_STEPS: frozenset[StepType] = frozenset(
    {
        StepType.PARSE,
        StepType.CHUNK,
        StepType.EMBED,
        StepType.STORE,
        StepType.CACHE_LOOKUP,
        StepType.REWRITE,
        StepType.ROUTE,
        StepType.DECOMPOSE,
        StepType.RETRIEVE,
        StepType.AUGMENT,
        StepType.SYNTHESIZE,
    }
)


async def _pause_for(step_type: StepType) -> None:
    """Hold a moment before a watched stage does its work.

    **Between stages, never inside a measurement.** The pause happens after the
    step has been recorded as running and before its body starts, so the card
    lights up, holds, and then fills with its real data. `duration_ms`, tokens and
    cost are timed across the body alone and are exactly what they would be with
    pacing off — which is the property that makes this honest enough to ship in a
    tool whose whole claim is that its numbers are real. The canvas says it is
    paced while it is.

    It exists because some stages are genuinely instantaneous. Parsing and chunking
    are local work of a few milliseconds; against the offline fake providers a
    whole ingest is about twenty. No polling interval makes that visible, and a
    class still has to see it happen.
    """
    ctx = trace_ctx.current()
    if ctx is None or not ctx.pace_ms or step_type not in PACED_STEPS:
        return
    await asyncio.sleep(ctx.pace_ms / 1000)


async def _open(step: AgentStep) -> None:
    """Record a step as in flight, before its body runs.

    **This is what makes a run watchable.** A step used to reach the store only
    when it completed, so the trace had no "started" signal at all: the canvas
    inferred which stage was in flight by marking the next pending one, and a
    student watching a document index saw a jump from empty to done rather than
    parse, then chunk, then embed. Writing on entry as well as on exit makes the
    running stage a measurement instead of a guess.

    The exit write replaces this row — same `id`, and `id` is the primary key in
    SQLite and matched by id in memory — so the finished trace is exactly what it
    was before this existed. Nothing downstream sees a duplicate.
    """
    await _emit(step)


def _open_soon(step: AgentStep) -> None:
    """`_open` from synchronous code.

    Best-effort by nature: inside a running loop this only reaches the store when
    the caller next yields, and a synchronous body never does. That is fine — the
    stages a class watches are all `atrace_step` regions, and this exists so the
    trace stays uniform rather than because a sync helper is watchable.
    """
    _emit_soon(step)


def traced(
    step_type: StepType,
    *,
    label: str | None = None,
    capture_input: bool = True,
    capture_output: bool = True,
    attributes_from: Callable[[Any], dict[str, Any]] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Record one `AgentStep` per call of the decorated function.

    Works on both coroutine and plain functions. `capture_input` /
    `capture_output` exist for the cases where a payload is large, binary, or
    simply uninteresting.

    **`attributes_from` is how a step says something specific about its result
    without capturing the whole thing.** The motivating case is embeddings, and it
    is worth stating precisely because the reasoning here used to be half right: a
    1,536-float vector genuinely does flood a trace view and teaches nothing —
    which is why `capture_output=False` stays — but the *first eight numbers* are
    the single most useful thing the platform can show a student who has just been
    told text becomes a vector. The blob is noise; the head is the lesson. A
    callable given the result, returning attributes, is the smallest way to keep
    both facts true at once.

    Failures in the extractor are swallowed. Deriving a display attribute must
    never break the call being observed, for the same reason `_emit` does not.
    """

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        step_label = label or fn.__qualname__

        def _extra(result: Any) -> dict[str, Any]:
            if attributes_from is None:
                return {}
            try:
                return attributes_from(result) or {}
            except Exception:  # noqa: BLE001
                logger.exception("attributes_from failed for %s", step_label)
                return {}

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
                step = _build_step(
                    step_type=step_type,
                    label=step_label,
                    raw_input=_render(_describe_call(args, kwargs)) if capture_input else None,
                    attributes={"function": fn.__qualname__},
                )
                await _open(step)
                started = time.perf_counter()
                try:
                    with trace_ctx.child_of(step.id):
                        result = await fn(*args, **kwargs)
                except BaseException as exc:
                    await _emit(
                        step.model_copy(
                            update={
                                "status": _status_for(exc),
                                "duration_ms": _elapsed_ms(started),
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                        )
                    )
                    raise
                await _emit(
                    step.model_copy(
                        update={
                            "status": StepStatus.OK,
                            "duration_ms": _elapsed_ms(started),
                            "raw_output": _render(result) if capture_output else None,
                            "usage": _usage_of(result),
                            "attributes": {**step.attributes, **_extra(result)},
                        }
                    )
                )
                return result

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
            step = _build_step(
                step_type=step_type,
                label=step_label,
                raw_input=_render(_describe_call(args, kwargs)) if capture_input else None,
                attributes={"function": fn.__qualname__},
            )
            _open_soon(step)
            started = time.perf_counter()
            try:
                with trace_ctx.child_of(step.id):
                    result = fn(*args, **kwargs)
            except BaseException as exc:
                _emit_soon(
                    step.model_copy(
                        update={
                            "status": _status_for(exc),
                            "duration_ms": _elapsed_ms(started),
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                )
                raise
            _emit_soon(
                step.model_copy(
                    update={
                        "status": StepStatus.OK,
                        "duration_ms": _elapsed_ms(started),
                        "raw_output": _render(result) if capture_output else None,
                        "usage": _usage_of(result),
                        "attributes": {**step.attributes, **_extra(result)},
                    }
                )
            )
            return result

        return sync_wrapper  # type: ignore[return-value]

    return decorator


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _describe_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """Render a call's arguments, dropping `self`.

    `self` is dropped because a provider or retriever instance reprs as a memory
    address at best, and at worst embeds its own configuration — including an API
    key — into the trace.
    """
    positional = args[1:] if args and hasattr(args[0], "__dict__") else args
    parts = [repr(a) for a in positional]
    parts += [f"{k}={v!r}" for k, v in kwargs.items()]
    return ", ".join(parts)


@contextlib.contextmanager
def trace_step(
    step_type: StepType,
    *,
    label: str,
    raw_input: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> Iterator[StepHandle]:
    """Trace a region of code rather than a whole function.

    The decorator covers the common case; this covers the ones it cannot reach —
    one iteration of a ReAct loop, or a router decision computed inline. The
    handle lets the body attach the output and usage it produced.
    """
    step = _build_step(
        step_type=step_type,
        label=label,
        raw_input=_truncate(raw_input) if raw_input else None,
        attributes=attributes or {},
    )
    _open_soon(step)
    handle = StepHandle(step_id=step.id)
    started = time.perf_counter()
    try:
        with trace_ctx.child_of(step.id):
            yield handle
    except BaseException as exc:
        _emit_soon(
            step.model_copy(
                update={
                    "status": _status_for(exc),
                    "duration_ms": _elapsed_ms(started),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        )
        raise
    _emit_soon(
        step.model_copy(
            update={
                "status": handle.status,
                "duration_ms": _elapsed_ms(started),
                "raw_output": _truncate(handle.output) if handle.output else None,
                "usage": handle.usage,
                "attributes": {**step.attributes, **handle.attributes},
            }
        )
    )


@contextlib.asynccontextmanager
async def atrace_step(
    step_type: StepType,
    *,
    label: str,
    raw_input: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> AsyncIterator[StepHandle]:
    """Async form of `trace_step`, awaiting the store write.

    Preferred inside pipelines: awaiting the write means the step has reached the
    store — and therefore the SSE subscribers — before the next step starts, which
    keeps the trace ordering a student sees faithful to execution order.

    **The stages a class watches are all opened here**, which is why this is where
    the teaching pause lives. See `_pause_for`.
    """
    step = _build_step(
        step_type=step_type,
        label=label,
        raw_input=_truncate(raw_input) if raw_input else None,
        attributes=attributes or {},
    )
    await _open(step)
    await _pause_for(step_type)
    handle = StepHandle(step_id=step.id)
    started = time.perf_counter()
    try:
        with trace_ctx.child_of(step.id):
            yield handle
    except BaseException as exc:
        await _emit(
            step.model_copy(
                update={
                    "status": _status_for(exc),
                    "duration_ms": _elapsed_ms(started),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        )
        raise
    await _emit(
        step.model_copy(
            update={
                "status": handle.status,
                "duration_ms": _elapsed_ms(started),
                "raw_output": _truncate(handle.output) if handle.output else None,
                "usage": handle.usage,
                "attributes": {**step.attributes, **handle.attributes},
            }
        )
    )


class StepHandle:
    """Write handle for a step that is still open."""

    def __init__(self, *, step_id: str) -> None:
        self.step_id = step_id
        self.output: str | None = None
        self.usage: Usage = Usage()
        self.status: StepStatus = StepStatus.OK
        self.attributes: dict[str, Any] = {}

    def set_output(self, text: str) -> None:
        self.output = text

    def add_usage(self, usage: Usage) -> None:
        self.usage = self.usage + usage

    def mark_budget_exceeded(self, reason: str) -> None:
        """Record a stop that was our decision, not a fault.

        Used when the agent loop halts on its iteration or tool budget and still
        produces a partial synthesis — Section 11 wants that rendered as
        "stopped: budget reached", not as an error.
        """
        self.status = StepStatus.BUDGET_EXCEEDED
        self.attributes["stopped_reason"] = reason

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value


__all__ = [
    "MAX_PAYLOAD_CHARS",
    "StepHandle",
    "atrace_step",
    "configure",
    "get_store",
    "trace_step",
    "traced",
]
