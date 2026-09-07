"""The single source of truth for configuration and secrets.

Two rules make this module the security boundary described in System Design
Section 6.5, priority 1:

1. Secrets are typed `SecretStr`. Pydantic renders them as `**********` in every
   repr, log line, and traceback — so leaking one requires an explicit
   `.get_secret_value()` call that a reviewer can grep for, rather than an
   accidental f-string.
2. Only the AI Backend imports `Settings`. The Frontend receives
   `FrontendSettings`, which has no secret field at all. A key cannot reach the
   browser because it is not in the object that gets there.

Validation is deliberately fail-fast and provider-aware: `validate_runtime()`
demands keys only for the providers actually selected, so an Ollama-only laptop
boots with no keys at all — which is what makes PRD Section 6's "fresh machine
with only API keys configured" criterion honestly satisfiable.
"""

from __future__ import annotations

import functools
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_backend.errors import ConfigurationError

# Providers that need a key from us, versus ones that do not. Ollama runs
# locally; `fake` is the in-process test double.
_KEYLESS_PROVIDERS = frozenset({"ollama", "fake", "none"})

# Anthropic publishes no embeddings API. Naming it here rather than discovering
# it at the first query is the difference between a boot-time error message and a
# confusing failure mid-demo.
_EMBEDDING_PROVIDERS = frozenset({"openai", "ollama", "fake"})
_LLM_PROVIDERS = frozenset({"openai", "anthropic", "ollama", "fake"})

# Providers whose adapter actually translates `ToolSpec` and parses tool calls back
# out. Ollama's `complete` accepts `tools=` and discards it — its `/api/chat` does
# support tools, but the adapter does not implement them.
#
# This matters more than a missing feature usually would. An agentic strategy would
# still *run* on Ollama: it would route, decompose, retrieve, and answer. The ReAct
# loop would offer a tool, get nothing back, and stop — so "Agentic RAG" would be
# Naive RAG with two extra LLM calls and a longer trace, and the one comparison this
# platform exists to teach would be measuring nothing.
#
# The consequence is scoped rather than fatal: Ollama plus Naive RAG is a perfectly
# good keyless configuration and boots normally. `runtime.py` reads this set and
# leaves the agentic strategies unregistered with a stated reason, so they appear
# unavailable rather than silently wrong.
TOOL_CAPABLE_PROVIDERS = frozenset({"openai", "anthropic", "fake"})


class LLMSettings(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    api_key: SecretStr | None = None
    base_url: str | None = None
    timeout_seconds: float = 60.0


class EmbeddingSettings(BaseModel):
    provider: str = "openai"
    model: str = "text-embedding-3-small"
    api_key: SecretStr | None = None
    base_url: str | None = None
    timeout_seconds: float = 30.0


class VisionSettings(BaseModel):
    """Image captioning at ingestion (System Design Section 10).

    `provider` and `model` default to empty, meaning "use whatever the LLM is
    configured as". Captioning is the same vendor and usually the same model as
    generation, so requiring a second block of configuration would be friction
    with no benefit — and an instructor who never uploads an image should not have
    to configure a vision provider at all.
    """

    provider: str = ""
    model: str = ""
    api_key: SecretStr | None = None
    base_url: str | None = None
    timeout_seconds: float = 90.0


class SearchSettings(BaseModel):
    provider: str = "none"
    api_key: SecretStr | None = None
    timeout_seconds: float = 15.0


class CapSettings(BaseModel):
    """Per-session limits — the most important control for a workshop.

    Enforced before each external call, never after. The agent-loop bounds
    (`max_agent_iterations`, `max_tool_calls_per_query`) are what turn "bounded
    iterations + tool budget" from System Design Section 10 into a number.
    """

    max_cost_usd_per_session: float = 2.00
    max_requests_per_session: int = 50
    max_llm_calls_per_query: int = 20
    max_agent_iterations: int = 5
    max_tool_calls_per_query: int = 8
    # Web searches per query. Low on purpose: each is a paid third-party request, and
    # a question needing more than three distinct searches is a question the router
    # should have decomposed rather than one the agent should keep searching for.
    max_search_calls_per_query: int = 3


class RetrievalSettings(BaseModel):
    """Chunking and retrieval knobs.

    Exposed as configuration rather than hard-coded because they are the most
    instructive dials in the system: raising `chunk_overlap_chars` visibly costs
    more to index, lowering `min_similarity` visibly stops the "nothing relevant
    found" path from ever firing, and toggling `hybrid` shows what keyword search
    contributes. A student changing one and re-running the evaluation learns more
    than any explanation of it.
    """

    top_k: int = 5
    # Cosine similarity floor. Below this a chunk is treated as irrelevant, which
    # is what makes an honest "I found nothing" possible.
    min_similarity: float = 0.25
    # Dense + BM25 fused by reciprocal rank (System Design Section 10). Off by
    # default so the dense baseline is what a first run measures; the evaluation
    # harness reports both.
    hybrid: bool = False
    chunk_chars: int = 1_200
    chunk_overlap_chars: int = 150


class CacheSettings(BaseModel):
    """The semantic cache — chapter 07's third pillar.

    **On by default, unlike the web route and the demo corpus.** Both of those are
    off because using them *spends* — a paid third-party call, four paid embedding
    round trips. This one only ever avoids spending, so the reasoning that gates
    them does not apply, and a cache an instructor has to switch on is a cache the
    class never sees. The sidebar toggle exists for the opposite case: charging full
    price for a question already asked, to show what the cache was saving.

    `min_similarity` is cosine and is compared against the closest stored question.
    chapter 07 uses a squared-L2 threshold of 0.2 on normalised vectors, which is
    cosine ≥ 0.90; this is stricter because the failure directions are not
    symmetric. A miss costs one query; a hit on a question that merely looked
    similar answers something the student did not ask, with citations, confidently.
    """

    enabled: bool = True
    min_similarity: float = 0.92
    # Per session, and bounded — unlike the reference implementation, which grows
    # without limit and rewrites its whole JSON file on every insert.
    max_entries: int = 64


class AgentSettings(BaseModel):
    """Switches for the orchestration stages, for a class that wants to isolate one.

    The rewriter is the only one here so far, and it has an off-switch for a
    teaching reason rather than a safety one: turning it off and re-asking a
    follow-up is the fastest way to show what it was doing. The step is still
    emitted when off, reporting `llm_called: false` — the same pattern the
    decomposer uses for a question the router called simple.
    """

    rewrite_enabled: bool = True


class DemoSettings(BaseModel):
    """The one-click corpus, and why it is off by default.

    Loading it indexes four documents through the configured embedding provider. On
    the fake provider that is free; on a real one it is a paid round trip per file,
    and the button sits in the sidebar where a curious student will click it — twice,
    on two sessions, in a room of twenty. An instructor turns it on for the class that
    needs it.

    Turning it off takes the labelled example questions with it. They predict outcomes
    measured against that specific corpus — "splitting this question finds a document
    the blended search misses" is only true of documents that make it true — so they
    are offered only once those documents are actually indexed. A prediction the
    harness cannot back is a prediction the product should not make.
    """

    documents_enabled: bool = False


class UploadSettings(BaseModel):
    max_files_per_session: int = 5
    max_bytes_per_file: int = 25 * 1024 * 1024
    # PPTX and XLSX are zip containers, so a small upload can expand enormously.
    # This is the zip-bomb ceiling from System Design Section 6.5, priority 3.
    max_uncompressed_bytes: int = 250 * 1024 * 1024
    allowed_extensions: tuple[str, ...] = (
        ".pdf",
        ".pptx",
        ".docx",
        ".xlsx",
        ".png",
        ".jpg",
        ".jpeg",
        ".md",
        ".txt",
    )


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    # Where the Frontend layer reaches the Backend layer. Both apps run in one
    # uvicorn process, but the hop is real HTTP (System Design Section 6.2).
    backend_base_url: str = "http://127.0.0.1:8000/api/v1"
    session_token_ttl_seconds: int = 4 * 60 * 60
    # CORS is restricted to the Frontend's own origin (Section 6.5, priority 6).
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:8000", "http://localhost:8000")


class StorageSettings(BaseModel):
    db_path: Path = Path("var/axis.sqlite")
    chroma_path: Path = Path("var/chroma")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AXIS_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm: LLMSettings = Field(default_factory=LLMSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    vision: VisionSettings = Field(default_factory=VisionSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    caps: CapSettings = Field(default_factory=CapSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    upload: UploadSettings = Field(default_factory=UploadSettings)
    demo: DemoSettings = Field(default_factory=DemoSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    log_level: str = "INFO"

    def validate_runtime(self) -> None:
        """Refuse to start on a configuration that cannot work.

        Called once during application startup. Every message names the exact
        environment variable to set, because the person reading it is usually an
        instructor twenty minutes before a class, not the author of this file.
        """
        problems: list[str] = []

        if self.llm.provider not in _LLM_PROVIDERS:
            problems.append(
                f"AXIS_LLM__PROVIDER={self.llm.provider!r} is not supported. "
                f"Choose one of: {', '.join(sorted(_LLM_PROVIDERS))}."
            )
        elif self.llm.provider not in _KEYLESS_PROVIDERS and not self.llm.api_key:
            problems.append(
                f"AXIS_LLM__API_KEY is required when AXIS_LLM__PROVIDER="
                f"{self.llm.provider!r}. Set it, or switch to "
                f"AXIS_LLM__PROVIDER=ollama to run with no API key."
            )

        if self.embedding.provider == "anthropic":
            problems.append(
                "AXIS_EMBEDDING__PROVIDER=anthropic is not possible: Anthropic "
                "publishes no embeddings API. Use openai or ollama for embeddings "
                "(the LLM provider can still be anthropic)."
            )
        elif self.embedding.provider not in _EMBEDDING_PROVIDERS:
            problems.append(
                f"AXIS_EMBEDDING__PROVIDER={self.embedding.provider!r} is not "
                f"supported. Choose one of: {', '.join(sorted(_EMBEDDING_PROVIDERS))}."
            )
        elif self.embedding.provider not in _KEYLESS_PROVIDERS and not self.embedding.api_key:
            problems.append(
                f"AXIS_EMBEDDING__API_KEY is required when "
                f"AXIS_EMBEDDING__PROVIDER={self.embedding.provider!r}."
            )

        if self.caps.max_cost_usd_per_session <= 0:
            problems.append(
                "AXIS_CAPS__MAX_COST_USD_PER_SESSION must be greater than 0; "
                "a zero or negative cap would reject every query."
            )
        # The agent-loop bounds. Unvalidated until Milestone 1, when they acquired a
        # consumer: a zero would make the ReAct loop unreachable while looking
        # configured, and the escalation path would silently never run.
        if self.caps.max_agent_iterations < 1:
            problems.append(
                "AXIS_CAPS__MAX_AGENT_ITERATIONS must be at least 1; zero would "
                "disable the agent loop while leaving the agentic strategies listed "
                "as available."
            )
        if self.caps.max_tool_calls_per_query < 1:
            problems.append("AXIS_CAPS__MAX_TOOL_CALLS_PER_QUERY must be at least 1.")
        # Three calls happen before anything is retrieved — rewrite, route,
        # decompose — and one more is needed for the answer. Below four, an agentic
        # query cannot complete at all.
        #
        # This floor was 3 until the rewriter was added, and the count is stated in
        # the message rather than left as a number so the next stage added in front
        # of retrieval has an obvious place to declare itself. With
        # `AXIS_AGENT__REWRITE_ENABLED=false` the rewrite call does not happen, but
        # the floor is not lowered for it: a cap that only works while an unrelated
        # feature is switched off is worse than a cap set one higher.
        minimum_llm_calls = 4
        if self.caps.max_llm_calls_per_query < minimum_llm_calls:
            problems.append(
                f"AXIS_CAPS__MAX_LLM_CALLS_PER_QUERY is "
                f"{self.caps.max_llm_calls_per_query}, but an agentic query needs at "
                f"least {minimum_llm_calls} (rewrite, route, decompose, synthesize)."
            )
        if self.upload.max_files_per_session < 1:
            problems.append("AXIS_UPLOAD__MAX_FILES_PER_SESSION must be at least 1.")

        if problems:
            raise ConfigurationError(
                "Axis cannot start with the current configuration.",
                detail="\n".join(f"  - {p}" for p in problems),
            )

    def secret_values(self) -> tuple[str, ...]:
        """Every configured secret, in plaintext, for the trace redactor.

        The one place that legitimately unwraps secrets. `observability/redact.py`
        uses this to guarantee no configured key can survive into a persisted
        `AgentStep`. Do not call it for any other purpose.
        """
        raw = (
            self.llm.api_key,
            self.embedding.api_key,
            self.vision.api_key,
            self.search.api_key,
            # **A key added to `Settings` and forgotten here survives into a persisted
            # `AgentStep`**, which is the one place CLAUDE.md says a secret must never
            # reach. Guarded by `test_every_configured_secret_is_redactable`, which
            # walks the model rather than trusting this list to be complete.
        )
        return tuple(s.get_secret_value() for s in raw if s and s.get_secret_value())

    def resolved_vision(self) -> VisionSettings:
        """Vision configuration, falling back to the LLM's.

        Applied here rather than in the registry so that `secret_values()` and the
        health check see the same resolution the provider will actually use.
        """
        return VisionSettings(
            provider=self.vision.provider or self.llm.provider,
            model=self.vision.model or self.llm.model,
            api_key=self.vision.api_key or self.llm.api_key,
            base_url=self.vision.base_url or self.llm.base_url,
            timeout_seconds=self.vision.timeout_seconds,
        )


class FrontendSettings(BaseModel):
    """What the Frontend layer is allowed to know.

    Structurally incapable of carrying a secret. Derived from `Settings` by
    `for_frontend()` rather than read from the environment, so there is exactly
    one narrowing point to audit.
    """

    backend_base_url: str
    max_files_per_session: int
    max_bytes_per_file: int
    allowed_extensions: tuple[str, ...]
    # Whether to offer the one-click corpus, and with it the labelled example
    # questions measured against it. See `DemoSettings`.
    demo_documents_enabled: bool = False


def for_frontend(settings: Settings) -> FrontendSettings:
    return FrontendSettings(
        backend_base_url=settings.server.backend_base_url,
        max_files_per_session=settings.upload.max_files_per_session,
        max_bytes_per_file=settings.upload.max_bytes_per_file,
        allowed_extensions=settings.upload.allowed_extensions,
        demo_documents_enabled=settings.demo.documents_enabled,
    )


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, read from the environment once.

    Cached so that every layer sees the same object. Tests call
    `get_settings.cache_clear()` to rebuild it under a patched environment.
    """
    return Settings()
