"""Shared test fixtures.

Three properties the whole suite depends on:

**Offline by construction.** `_no_real_network` is autouse and fails any test that
opens a real socket. PRD Section 7 lists non-deterministic LLM output as a live
risk; a test suite that could reach a real provider would inherit that risk and
fail on Tuesdays for reasons nobody can reproduce. Making the network
*impossible* rather than merely discouraged is what keeps that from happening by
accident.

**Isolated per test.** Every test builds its own app, with an in-memory database
and an in-memory step store. Acceptance tests therefore run in any order and
leave nothing behind.

**Milestone-selectable.** `--milestone=N` runs only the tests expected to pass at
that milestone. Note that pytest marker expressions (`-m`) cannot match a
marker's arguments, so `-m "milestone(0)"` does not work — hence the explicit
option implemented in `pytest_collection_modifyitems` below.
"""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI

from ai_backend.config.settings import Settings
from ai_backend.observability import trace as trace_module
from ai_backend.observability.store import InMemoryStepStore
from ai_backend.providers.fake import (
    FakeEmbeddingProvider,
    FakeLLMProvider,
    FakeSearchProvider,
)
from backend.app import create_app as create_backend_app
from backend.store.db import Database
from frontend.app import create_app as create_frontend_app

# ---------------------------------------------------------------------------
# Milestone selection
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--milestone",
        action="store",
        default=None,
        help=(
            "Run only tests marked for this milestone, e.g. --milestone=-1. "
            "Tests with no milestone marker always run."
        ),
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    raw = config.getoption("--milestone")
    if raw is None:
        return
    target = int(raw)

    skip = pytest.mark.skip(reason=f"not part of milestone {target}")
    for item in items:
        marker = item.get_closest_marker("milestone")
        # Unmarked tests (unit, contract) always run: they are the foundation
        # every milestone stands on.
        if marker is None:
            continue
        if marker.args and marker.args[0] != target:
            item.add_marker(skip)


# ---------------------------------------------------------------------------
# Network lockdown
# ---------------------------------------------------------------------------


_LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0"}


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly on any attempt to reach a host off this machine.

    Patches `socket.socket.connect` rather than a particular HTTP client, so it
    catches every route out: httpx, urllib, or a vendor SDK someone adds later.
    ASGI transports and `respx` mocks never touch a socket and are unaffected.

    Loopback is permitted, which is a necessary carve-out rather than a
    concession: on Windows, asyncio's `ProactorEventLoop` builds its internal
    self-pipe with `socket.socketpair()`, which connects over 127.0.0.1. Blocking
    that would make it impossible to create an event loop at all, and every async
    test would fail in fixture setup.

    The guard therefore stops what actually matters — a test reaching
    api.openai.com or api.anthropic.com — while allowing purely local plumbing.
    """
    real_connect = socket.socket.connect

    def _guarded(self: socket.socket, address: object, *args: object) -> object:
        host: object = None
        if isinstance(address, tuple) and address:
            host = address[0]
        if host is None or str(host) in _LOOPBACK:
            return real_connect(self, address, *args)  # type: ignore[arg-type]
        raise AssertionError(
            f"A test tried to connect to {host!r}. Tests must not reach the "
            f"network: use the fake providers or a respx mock transport — see "
            f"tests/conftest.py."
        )

    monkeypatch.setattr(socket.socket, "connect", _guarded)


# ---------------------------------------------------------------------------
# Configuration lockdown
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_ambient_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cut every test off from the developer's own configuration.

    This is a leak fix, not tidiness. `env_file` lives in `model_config`, so
    *every* `Settings(...)` reads `.env` — constructing it directly with explicit
    keyword arguments does not opt out, it only overrides the fields it names.
    Anything left unset falls through to the developer's file.

    The consequence was concrete: a test asserting `secret_values() == ()` passed
    `llm={"api_key": None}` but said nothing about `embedding`, so a real
    `AXIS_EMBEDDING__API_KEY` was picked up and pytest printed the live OpenAI key
    verbatim in the assertion diff. `SecretStr` cannot help here — the whole
    purpose of `secret_values()` is to return the unmasked strings.

    A pytest diff is a bad place for a key: terminal scrollback, `--last-failed`
    caches, and CI logs all keep it. So the environment is emptied rather than
    trusted to be empty, which also makes the suite behave the same on a machine
    with no `.env` at all — the state a fresh checkout is in.
    """
    for name in [key for key in os.environ if key.startswith("AXIS_")]:
        monkeypatch.delenv(name, raising=False)
    # Read per-instantiation by pydantic-settings, so patching the dict is enough.
    monkeypatch.setitem(Settings.model_config, "env_file", None)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@pytest.fixture
def settings() -> Settings:
    """Test settings: fake providers, in-memory database, small caps.

    Caps are deliberately tiny so a cap-related test does not have to make fifty
    requests to reach one. Ambient configuration is neutralised by
    `_no_ambient_config` above — not by constructing `Settings` directly, which
    does not achieve it.
    """
    return Settings(
        llm={"provider": "fake", "model": "fake-model"},
        embedding={"provider": "fake", "model": "fake-embedding"},
        search={"provider": "fake"},
        caps={
            "max_cost_usd_per_session": 1.00,
            "max_requests_per_session": 5,
            "max_llm_calls_per_query": 4,
            "max_agent_iterations": 2,
            "max_tool_calls_per_query": 3,
        },
        upload={"max_files_per_session": 5},
        # On, unlike production. The corpus is what the labelled predicted outcomes
        # were measured against, so the suite has to be able to index it — and against
        # the fake providers that costs nothing, which is the only reason it is off by
        # default at all.
        demo={"documents_enabled": True},
        storage={"db_path": ":memory:"},
        log_level="WARNING",
    )


@pytest.fixture
def harness_verdict(tmp_path, monkeypatch, settings: Settings):
    """A recorded harness verdict in which all four mechanisms still pay off.

    **Needed because a pain-point card no longer asserts its own measurement.** It reads
    `ceilings.json`, and a record measured under other conditions counts as no record —
    which is the point of the mechanism and also means the suite, on fake providers,
    would otherwise see every card unverified. So a test that is about the *card* rather
    than about the verdict says "given the harness has verified these" by requesting
    this.

    Patched into `tmp_path` rather than written to the real file: the committed
    `ceilings.json` is a record of a measurement somebody paid for, and a test run must
    not overwrite it with fake-provider figures.

    The figures are the ones actually measured under the fake embedder, where a blended
    compound query falls below `min_similarity` and returns nothing — 0.00 asked whole
    against 1.00 for the ground truth. Real numbers rather than invented ones, so a test
    reading them is reading something that once happened.
    """
    from ai_backend.evaluation.verdict import (
        CeilingVerdict,
        QuestionDelta,
        write_verdict,
    )

    path = tmp_path / "ceilings.json"
    monkeypatch.setattr("ai_backend.evaluation.verdict.VERDICT_FILE", path)

    def held(unit: str, question_id: str, before: float) -> CeilingVerdict:
        return CeilingVerdict(
            unit=unit,
            improved=1,
            eligible=1,
            questions=[
                QuestionDelta(question_id=question_id, before=before, after=1.0)
            ],
        )

    return write_verdict(
        {
            "decomposition": held("recall", "ceiling-vs-nte", 0.0),
            "hop": held("recall", "deliverable-at-risk", 0.0),
            "resolution": held("recall", "agreement-term", 0.0),
            "coverage": held("coverage", "summarize-program", 0.13),
        },
        settings=settings,
        path=path,
    )


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_llm() -> FakeLLMProvider:
    """A scriptable LLM whose `call_count` is the suite's key assertion.

    Proving "no LLM call was made" needs an observable that counts calls; a
    response body cannot evidence a call that did not happen.
    """
    return FakeLLMProvider(responses=["A fake grounded answer [1]."])


@pytest.fixture
def fake_embeddings() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


@pytest.fixture
def fake_search() -> FakeSearchProvider:
    return FakeSearchProvider()


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------


@pytest.fixture
def database() -> Iterator[Database]:
    db = Database(":memory:")
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def step_store() -> Iterator[InMemoryStepStore]:
    """An in-memory step store, wired in as the process-wide sink.

    `trace_module.configure` sets a module global, so the previous store is
    restored afterwards to keep tests independent.
    """
    store = InMemoryStepStore()
    previous = trace_module.get_store()
    trace_module.configure(store=store)
    try:
        yield store
    finally:
        trace_module.configure(store=previous)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------


@pytest.fixture
def backend_app(
    settings: Settings,
    database: Database,
    step_store: InMemoryStepStore,
    fake_llm: FakeLLMProvider,
    fake_embeddings: FakeEmbeddingProvider,
) -> FastAPI:
    """A fully-wired Backend using the *fixture* providers.

    The runtime builds its own fake providers from settings, which would leave the
    `fake_llm` fixture observing an object nothing ever calls — so
    `fake_llm.call_count == 0` would pass vacuously in every test that asserts it.
    Swapping them in afterwards makes those assertions mean something, and lets a
    test script the model's response.

    This works because `AiRuntime` registers a pipeline *factory* that reads
    `self.llm` when called, not a pipeline holding a captured provider. If that
    ever changes to eager construction, this override silently stops taking
    effect — hence the assertion below.
    """
    app = create_backend_app(
        settings=settings, database=database, step_store=step_store
    )
    if app.state.ai is not None:
        app.state.ai.llm = fake_llm
        app.state.ai.embeddings = fake_embeddings
        # The retriever captured the original embedder at construction, so point
        # it at the fixture's too.
        app.state.ai.retriever._embeddings = fake_embeddings  # noqa: SLF001
        assert app.state.ai.llm is fake_llm
    return app


@pytest.fixture
async def api(backend_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """A client for the Backend app alone.

    `base_url` carries no `/api/v1` prefix: this talks to the backend app
    directly, and the prefix comes from the mount in `axis/asgi.py`. Tests using
    this fixture therefore call `/health`, not `/api/v1/health`.

    No lifespan juggling is needed — `create_app()` wires everything
    synchronously, precisely because `ASGITransport` never fires lifespan events.
    """
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=backend_app),
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
def composed_app(
    backend_app: FastAPI, settings: Settings
) -> FastAPI:
    """The full three-layer app, mounted exactly as `python -m axis` builds it.

    Built here rather than imported from `axis.asgi`, because that module's
    top-level `app` reads the ambient environment and would pick up a
    developer's own `.env`. This one is injected with test settings and an
    in-memory store, but the mount structure is identical.
    """
    frontend = create_frontend_app(
        settings=settings,
        transport=httpx.ASGITransport(app=backend_app),
        backend_base_url="http://axis-backend.internal",
        shared_state=backend_app.state,
    )
    root = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    root.mount("/api/v1", backend_app)
    root.mount("/", frontend)
    return root


@pytest.fixture
async def client(composed_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """A client for the whole composed app, using real `/api/v1/...` paths.

    This is the fixture acceptance tests should prefer: it exercises the same
    routing a browser would, including the mount.
    """
    transport = httpx.ASGITransport(app=composed_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


@pytest.fixture
async def session(client: httpx.AsyncClient) -> dict[str, object]:
    """A created session, with its bearer token."""
    response = await client.post("/api/v1/sessions", json={})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def auth(session: dict[str, object]) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['token']}"}


@pytest.fixture
def spend_to_cap(backend_app: FastAPI):
    """Drive a session's recorded spend up to (or past) its cost cap.

    Goes through `record_spend` — the same path real spending takes — rather than
    writing the row directly, so the test exercises the production ledger instead
    of a shortcut around it.
    """

    def _spend(session_id: str, amount: str | None = None) -> None:
        sessions = backend_app.state.sessions
        record = sessions.get(session_id)
        assert record is not None
        target = Decimal(amount) if amount else record.cap_cost_usd
        sessions.record_spend(session_id, cost_usd=target)

    return _spend
