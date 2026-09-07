"""Composition root: the two ASGI apps, one process.

The topology decided at Milestone -1 and recorded in System Design Section 6.2:

    root FastAPI
      ├── mount "/api/v1"  → backend app     (its own routes, own OpenAPI)
      └── mount "/"        → frontend app    (templates, static, SSE proxy)

Two apps, not one, and one process, not two. Each half of that is a deliberate
trade:

**Two apps** keeps the Frontend → Backend hop real HTTP. The Frontend could
import Backend service functions directly and save a round trip, but then the
REST/SSE contract in the Container diagram would never be exercised, and the
layer boundary would be a naming convention. Here it is load-bearing: the
Frontend has no import path to a provider or a secret.

**One process** is the classroom-reliability property. `python -m axis` starts
everything; there is one thing to keep alive during a live demo, and no
possibility of the Frontend running while the Backend is dead.

Mount order matters. `"/"` matches everything, so it has to be registered last
or it would shadow `/api/v1`.
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from ai_backend.config.settings import Settings, get_settings
from backend.app import create_app as create_backend_app
from frontend.app import create_app as create_frontend_app

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()

    root = FastAPI(
        title="Axis",
        version="0.1.0",
        # Documentation lives on the child apps (/api/v1/docs); the root is only
        # a mount point and has no routes of its own to describe.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    backend_app = create_backend_app(settings=resolved)

    # The Frontend calls the Backend through an ASGI transport pointed at the
    # backend app rather than out to a socket. Real HTTP semantics — headers, status
    # codes, JSON serialisation — with no dependency on the port actually being
    # bound, which also means no chicken-and-egg problem during startup.
    #
    # **One thing it cannot carry: an open-ended response.** `ASGITransport` buffers
    # a body to completion, so the Backend's SSE trace stream is unreadable through
    # it — it hangs rather than failing, which is worse. That is why the live canvas
    # polls `/trace/recent` instead of proxying the stream, and why
    # `trace_event_stream` is tested against the generator directly rather than over
    # HTTP. This comment used to claim SSE framing worked here; it does not.
    frontend_app = create_frontend_app(
        settings=resolved,
        transport=httpx.ASGITransport(app=backend_app),
        # No /api/v1 here: the transport talks to backend_app directly, and that
        # app's routes are prefix-free — the prefix comes from the mount below.
        # The host is arbitrary; ASGITransport never resolves it.
        backend_base_url="http://axis-backend.internal",
        shared_state=backend_app.state,
    )

    root.mount(API_PREFIX, backend_app)
    root.mount("/", frontend_app)
    return root


# The module-level app uvicorn imports: `uvicorn axis.asgi:app`.
app = create_app()
