"""Backend application factory.

`create_app()` rather than a module-level `app`, so tests can build an isolated
instance with an in-memory database and an in-memory step store instead of
mutating global state. Every acceptance test gets its own app, which is why they
can run in any order.

**Wiring happens in `create_app()`, not in a lifespan handler.** That is a
deliberate choice with a testing consequence: `httpx.ASGITransport` does not run
ASGI lifespan events, so anything set up in a `lifespan` hook would be missing
under test and present in production — the worst possible split. Building
everything synchronously means the app is fully formed the moment the factory
returns, and the test suite exercises exactly the object that serves traffic.
The lifespan hook is left for logging and teardown only.

Startup does four things, in order:

1. read and validate configuration (recording the problem, not raising)
2. open the SQLite store and apply migrations
3. point the observability library at its step store
4. register whichever strategy pipelines exist at this milestone

Step 1 records rather than raises. A refusal to boot would also take out
`/api/v1/health`, and an instructor debugging a bad `.env` twenty minutes before
class needs the health endpoint to be the thing that tells them what is wrong.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai_backend.config.settings import Settings, get_settings
from ai_backend.contracts.models import Strategy
from ai_backend.errors import AxisError, ConfigurationError
from ai_backend.observability import trace as trace_module
from ai_backend.observability.store import (
    AgentStepStore,
    InMemoryStepStore,
    SqliteStepStore,
)
from ai_backend.pipelines import available as available_strategies
from backend.api.v1 import api_router
from backend.core.errors import register_exception_handlers
from backend.core.middleware import RequestContextMiddleware
from backend.dispatch import AiRuntime, build_runtime
from backend.store.db import Database
from backend.store.repositories import (
    ComparisonRunRepository,
    ConversationRepository,
    DocumentRepository,
    QueryRunRepository,
    SessionRepository,
)

logger = logging.getLogger("axis.backend")


def create_app(
    *,
    settings: Settings | None = None,
    database: Database | None = None,
    step_store: AgentStepStore | None = None,
) -> FastAPI:
    """Build the Backend ASGI app, fully wired.

    Every collaborator is injectable, which is what lets the suite run against an
    in-memory database and step store with no patching of module globals.
    """
    resolved = settings or get_settings()
    owns_database = database is None

    # (1) Validate, but stay up. See the module docstring.
    config_error: str | None = None
    try:
        resolved.validate_runtime()
    except ConfigurationError as exc:
        config_error = f"{exc.message}\n{exc.detail or ''}".strip()
        logger.error("Configuration is not valid:\n%s", config_error)

    # (2) Store.
    db = database or Database(resolved.storage.db_path)

    # (3) Observability. Secrets are handed to the store so the redactor can
    # guarantee no configured key survives into a persisted step.
    store = step_store or _build_step_store(resolved)
    trace_module.configure(store=store)

    # (4) The AI Backend. Constructing it registers the strategy pipelines that
    # exist at this milestone, so "which strategies are available" follows from
    # what was actually wired rather than a list that could disagree.
    #
    # Skipped when configuration is invalid: building it would raise on a missing
    # key and take out /api/v1/health, which is the one endpoint that can explain
    # the problem. Strategies then report unavailable, which is accurate.
    ai: AiRuntime | None = None
    if config_error is None:
        try:
            ai = build_runtime(resolved)
        except AxisError as exc:
            config_error = f"{exc.message}\n{exc.detail or ''}".strip()
            logger.error("Could not initialise the AI Backend:\n%s", config_error)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        strategies = [s.value for s in available_strategies()]
        logger.info(
            "Axis backend ready — %d/%d strategies available%s",
            len(strategies),
            len(Strategy),
            f" ({', '.join(strategies)})" if strategies else "",
        )
        yield
        if owns_database:
            db.close()

    app = FastAPI(
        title="Axis API",
        version="0.1.0",
        description=(
            "Compares Naive RAG and Agentic RAG on cost, latency, and answer quality."
        ),
        lifespan=lifespan,
    )

    app.state.settings = resolved
    app.state.config_error = config_error
    app.state.db = db
    app.state.step_store = store
    app.state.ai = ai
    app.state.sessions = SessionRepository(db)
    app.state.documents = DocumentRepository(db)
    app.state.query_runs = QueryRunRepository(db)
    app.state.comparisons = ComparisonRunRepository(db)
    # What this session has asked, read back out of `query_run` — see
    # `store/migrations/002_conversation.sql` for why there is no `turn` table.
    app.state.conversation = ConversationRepository(db)

    # CORS restricted to the Frontend's own origin (System Design Section 6.5,
    # priority 6). Not "*": the trace stream carries a student's questions and
    # the contents of their documents.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.server.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router)
    return app


def _build_step_store(settings: Settings) -> AgentStepStore:
    """The trace store — SQLite, or in-memory when there is nowhere to persist.

    **`:memory:` cannot use `SqliteStepStore`, and the failure was silent.**
    `_connect()` opens a fresh connection per operation, which is correct for a file
    and fatal for `:memory:`: every connection to `:memory:` is its own empty
    database, so the schema created in the constructor was discarded and every later
    read hit `no such table: agent_step`. The app started, served its page, indexed a
    document, and 500'd the moment anything asked for the trace.

    Nothing caught it because the whole suite injects `InMemoryStepStore` directly —
    so the branch that picks a store was never exercised by a test, and `:memory:` is
    a documented, supported value (`_build_vector_store` in `ai_backend/runtime.py`
    makes exactly this choice, for exactly this reason). Found by running the app.
    """
    if str(settings.storage.db_path) == ":memory:":
        return InMemoryStepStore()
    return SqliteStepStore(
        settings.storage.db_path, secrets=settings.secret_values()
    )
