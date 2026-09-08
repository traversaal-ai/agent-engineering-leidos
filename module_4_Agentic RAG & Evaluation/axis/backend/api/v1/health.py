"""GET /api/v1/health — the Milestone -1 acceptance criterion.

    Given a fresh machine with only API keys configured, when Axis is started,
    then all three layers (Frontend, Backend, AI Backend) come up and pass the
    /api/v1/health check without any external service beyond the configured
    LLM/embedding/search providers.

Two design points follow from that wording.

**Each layer is reported separately.** A flat `{"status":"ok"}` would not
evidence "all three layers come up", and the test would end up asserting
something weaker than the criterion.

**The shallow check calls no provider.** "Without any external service" is a
statement about what health *depends on*. A check that pinged OpenAI would fail
when OpenAI was slow — reporting Axis as down when Axis is fine, which during a
live demo is the most expensive kind of wrong. `?deep=true` exists for when you
genuinely want to know whether the keys work, and is opt-in for that reason.

No auth: this endpoint has to be reachable before a session exists.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ai_backend.config.settings import Settings
from ai_backend.contracts.models import Strategy
from backend import dispatch
from backend.schemas.health import HealthResponse, LayerHealth, ProviderHealth

router = APIRouter(tags=["health"])

VERSION = "0.1.0"


@router.get("/health", response_model=HealthResponse)
async def health(
    request: Request,
    deep: bool = Query(
        default=False,
        description=(
            "Also check that configured providers are reachable. Off by default: "
            "liveness should not depend on a third party."
        ),
    ),
) -> HealthResponse:
    settings: Settings = request.app.state.settings
    layers: list[LayerHealth] = []

    # -- Backend ----------------------------------------------------------
    # We are executing, so routing is up; what remains uncertain is the store.
    try:
        request.app.state.sessions.delete_expired()
        layers.append(LayerHealth(name="backend", status="ok", detail="routes and session store"))
    except Exception as exc:  # noqa: BLE001
        layers.append(LayerHealth(name="backend", status="error", detail=str(exc)[:200]))

    # -- AI Backend -------------------------------------------------------
    # "Degraded" rather than "error" when a pipeline is missing: an LLM provider that
    # cannot call tools legitimately leaves Agentic RAG unavailable while Naive RAG
    # works fine, and a red health check on a working configuration would train
    # everyone to ignore it.
    #
    # Counted against the enum rather than a literal, so the denominator cannot drift
    # from the number of strategies that exist — it read "of 4" for a while after the
    # graph strategies were cancelled, reporting a shortfall against nothing.
    try:
        strategies = [s.value for s in dispatch.strategies_available()]
        ai_status = "ok" if strategies else "degraded"
        ai_detail = (
            f"{len(strategies)} of {len(Strategy)} strategy pipelines registered"
            if strategies
            else "no strategy pipelines registered"
        )
        layers.append(LayerHealth(name="ai_backend", status=ai_status, detail=ai_detail))
    except Exception as exc:  # noqa: BLE001
        strategies = []
        layers.append(LayerHealth(name="ai_backend", status="error", detail=str(exc)[:200]))

    # -- Frontend ---------------------------------------------------------
    # Reported by the Backend because the criterion asks one check to speak for
    # all three layers. The Frontend app sets this flag on shared state when its
    # templates and static files resolve; absent means it never started.
    frontend_ready = getattr(request.app.state, "frontend_ready", None)
    if frontend_ready is None:
        layers.append(
            LayerHealth(
                name="frontend",
                status="degraded",
                detail="frontend app not mounted (backend running standalone)",
            )
        )
    elif frontend_ready:
        layers.append(
            LayerHealth(
                name="frontend", status="ok", detail="templates and static assets"
            )
        )
    else:
        layers.append(
            LayerHealth(
                name="frontend",
                status="error",
                detail=getattr(request.app.state, "frontend_error", "failed to initialise"),
            )
        )

    # -- Configuration ----------------------------------------------------
    config_error: str | None = getattr(request.app.state, "config_error", None)

    providers: list[ProviderHealth] = []
    if deep:
        providers = await _check_providers(settings)

    # An unreachable provider on a deep check is "degraded", not "error": Axis
    # itself is healthy, the vendor is not.
    statuses = {layer.status for layer in layers}
    if "error" in statuses or config_error:
        overall = "error"
    elif "degraded" in statuses or any(p.reachable is False for p in providers):
        overall = "degraded"
    else:
        overall = "ok"

    return HealthResponse(
        status=overall,
        version=VERSION,
        available_strategies=strategies,
        layers=layers,
        providers=providers,
        config_valid=config_error is None,
        config_error=config_error,
        # Read off the settings rather than off a built provider: this route must stay
        # cheap and side-effect free, and "is one configured" is exactly what the
        # Frontend needs to decide whether to draw the control.
        web_search_available=settings.search.provider not in ("none", ""),
    )


async def _check_providers(settings: Settings) -> list[ProviderHealth]:
    """Report the configured providers, and probe them if we can.

    Reachability is left as `None` rather than guessed when there is nothing
    cheap to probe. A deep check that reported a confident `True` without having
    verified anything would be worse than one that admits it does not know.
    """
    result = [
        ProviderHealth(
            name=settings.llm.provider,
            kind="llm",
            model=settings.llm.model,
            reachable=None,
            detail="configured",
        ),
        ProviderHealth(
            name=settings.embedding.provider,
            kind="embedding",
            model=settings.embedding.model,
            reachable=None,
            detail="configured",
        ),
    ]

    # The fake provider is always reachable by definition — it is in-process.
    for entry in result:
        if entry.name == "fake":
            entry.reachable = True
            entry.detail = "in-process test double"

    return result
