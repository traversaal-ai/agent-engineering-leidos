"""The strategy registry — two slots, both filled.

    naive_rag    VectorRetriever, single-shot
    agentic_rag  the same retriever, plus router, decomposer, rewriter, cache, ReAct loop

Both are registered at startup by `runtime.py`, so in a working configuration
`available()` returns both. A slot can still empty at runtime, and the two ways it
happens want different messages:

- `mark_unavailable` — built, but unusable as configured (an LLM provider whose adapter
  cannot call tools cannot run an agentic strategy). Carries a reason naming the fix.
- `unregister` — test teardown only.

Asking for either case is a clear refusal rather than a 500 (System Design Section 14).

**This registry once held four slots**, two of them permanently `None` for a graph
retrieval column that was specified and never built. That column is a non-goal now (PRD
Section 3), so the "stretch goal" vocabulary and the schedule table it needed are gone
with it. Do not declare a `Strategy` before its pipeline exists: an unregistered member
is a 501 that reads like a bug, and the enum is not a roadmap.
"""

from __future__ import annotations

from collections.abc import Callable

from ai_backend.contracts.models import Strategy
from ai_backend.contracts.pipeline import Pipeline
from ai_backend.errors import UnsupportedStrategyError

# Populated by `register()` at startup.
_registry: dict[Strategy, Callable[[], Pipeline]] = {}

# A strategy that is built but cannot run under the current configuration, with the
# reason. Distinct from simply being absent: "not written yet" and "your provider
# cannot call tools" are different problems with different fixes, and a student told
# the wrong one goes looking in the wrong place.
_unavailable: dict[Strategy, str] = {}


def register(strategy: Strategy, factory: Callable[[], Pipeline]) -> None:
    _registry[strategy] = factory
    _unavailable.pop(strategy, None)


def mark_unavailable(strategy: Strategy, reason: str) -> None:
    """Declare a built strategy unusable under this configuration.

    Added at Milestone 1 for the agentic strategies on a provider whose adapter
    cannot call tools. Refusing to boot outright would be wrong — Ollama plus Naive
    RAG is a perfectly good keyless configuration and should run — but registering
    the strategy anyway would present Naive RAG's behaviour under an agentic label,
    which breaks the one comparison the platform teaches.

    Leaving it unregistered with a stated reason reuses machinery that already
    exists: the health endpoint reports it, the Frontend greys it out, and asking
    for it returns an explanation instead of a wrong answer.
    """
    _registry.pop(strategy, None)
    _unavailable[strategy] = reason


def unregister(strategy: Strategy) -> None:
    """Remove a registration.

    Exists for tests, which register a stub pipeline to prove the surrounding
    machinery (cap enforcement, tracing, dispatch) works before any real strategy
    is built, and must not leak that stub into the next test.
    """
    _registry.pop(strategy, None)
    _unavailable.pop(strategy, None)


def available() -> tuple[Strategy, ...]:
    """Strategies that can actually run right now.

    Both, in a working configuration. The Frontend gates its radios on this, so a
    strategy `mark_unavailable` has taken out is shown as unavailable rather than
    offered and then refused — a dead control in a live demo invites "why doesn't that
    work?", which is not a question the demo exists to answer.

    Iteration order follows the enum, not the registry, so the two always appear
    baseline-first regardless of the order `runtime.py` happened to register them in.
    """
    return tuple(s for s in Strategy if s in _registry)


def get_pipeline(strategy: Strategy) -> Pipeline:
    factory = _registry.get(strategy)
    if factory is None:
        reason = _unavailable.get(strategy)
        if reason is not None:
            raise UnsupportedStrategyError(
                f"The {strategy.value!r} strategy cannot run with the current "
                f"configuration.",
                detail=reason,
            )
        # Both strategies are registered at startup, so reaching here means one was
        # taken out of the registry without a reason recorded — `unregister` in a test,
        # or a `runtime.py` that failed to wire it. Say that plainly rather than
        # inventing a schedule: there is no roadmap left for this to be waiting on.
        raise UnsupportedStrategyError(
            f"The {strategy.value!r} strategy is not registered.",
            detail=f"Currently available: "
            f"{', '.join(s.value for s in available()) or 'none'}.",
        )
    return factory()


__all__ = [
    "available",
    "get_pipeline",
    "mark_unavailable",
    "register",
    "unregister",
]
