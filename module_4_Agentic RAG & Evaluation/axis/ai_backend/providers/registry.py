"""Provider resolution from configuration.

The only place in Axis that maps a provider *name* to a provider *class*. Every
pipeline receives an already-constructed `LLMProvider` / `EmbeddingProvider`, so
no pipeline ever contains the string "openai" — which is CLAUDE.md's "never
hardcode a specific provider inside a pipeline", enforced by there being no other
place the mapping exists.

Errors here are raised at startup, with the exact environment variable named. The
person reading the message is usually setting Axis up shortly before teaching
with it, and "KeyError: 'anthropic'" would not help them.
"""

from __future__ import annotations

import httpx

from ai_backend.config.settings import Settings
from ai_backend.contracts.providers import (
    EmbeddingProvider,
    LLMProvider,
    SearchProvider,
    VisionProvider,
)
from ai_backend.errors import ConfigurationError
from ai_backend.providers.anthropic_provider import (
    AnthropicLLMProvider,
    AnthropicVisionProvider,
)
from ai_backend.providers.fake import (
    FakeEmbeddingProvider,
    FakeLLMProvider,
    FakeSearchProvider,
    FakeVisionProvider,
)
from ai_backend.providers.ollama_provider import OllamaEmbeddingProvider, OllamaLLMProvider
from ai_backend.providers.openai_provider import (
    OpenAIEmbeddingProvider,
    OpenAILLMProvider,
    OpenAIVisionProvider,
)
from ai_backend.providers.search import CachedSearchProvider, SerpApiSearchProvider


def build_llm_provider(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> LLMProvider:
    cfg = settings.llm
    key = cfg.api_key.get_secret_value() if cfg.api_key else None
    common = {
        "model": cfg.model,
        "api_key": key,
        "base_url": cfg.base_url,
        "timeout_seconds": cfg.timeout_seconds,
        "transport": transport,
    }

    match cfg.provider:
        case "openai":
            return OpenAILLMProvider(**common)  # type: ignore[arg-type]
        case "anthropic":
            return AnthropicLLMProvider(**common)  # type: ignore[arg-type]
        case "ollama":
            return OllamaLLMProvider(**common)  # type: ignore[arg-type]
        case "fake":
            return FakeLLMProvider(model=cfg.model)
        case unknown:
            raise ConfigurationError(
                f"AXIS_LLM__PROVIDER={unknown!r} is not a provider Axis knows.",
                detail="Supported values: openai, anthropic, ollama, fake.",
            )


def build_embedding_provider(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> EmbeddingProvider:
    cfg = settings.embedding
    key = cfg.api_key.get_secret_value() if cfg.api_key else None
    common = {
        "model": cfg.model,
        "api_key": key,
        "base_url": cfg.base_url,
        "timeout_seconds": cfg.timeout_seconds,
        "transport": transport,
    }

    match cfg.provider:
        case "openai":
            return OpenAIEmbeddingProvider(**common)  # type: ignore[arg-type]
        case "ollama":
            return OllamaEmbeddingProvider(**common)  # type: ignore[arg-type]
        case "fake":
            return FakeEmbeddingProvider(model=cfg.model)
        case "anthropic":
            # Caught by Settings.validate_runtime() at startup too. Repeated here
            # because this function is also called directly in tests and
            # notebooks, and the explanation is what makes it actionable.
            raise ConfigurationError(
                "Anthropic publishes no embeddings API, so it cannot be used as "
                "AXIS_EMBEDDING__PROVIDER.",
                detail=(
                    "Set AXIS_EMBEDDING__PROVIDER=openai or =ollama. The LLM "
                    "provider can still be anthropic — the two are configured "
                    "independently for exactly this reason."
                ),
            )
        case unknown:
            raise ConfigurationError(
                f"AXIS_EMBEDDING__PROVIDER={unknown!r} is not a provider Axis knows.",
                detail="Supported values: openai, ollama, fake.",
            )


def build_vision_provider(
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> VisionProvider:
    """Resolve the image-captioning provider.

    Defaults to the LLM's provider and model, so an image upload works without any
    extra configuration. Ollama is refused rather than silently substituted:
    captioning needs a vision-capable local model (llava and friends) and the
    `/api/chat` image field differs enough to warrant its own adapter, which no
    milestone has needed yet. Naming that plainly beats a confusing empty caption.
    """
    cfg = settings.resolved_vision()
    key = cfg.api_key.get_secret_value() if cfg.api_key else None
    common = {
        "model": cfg.model,
        "api_key": key,
        "base_url": cfg.base_url,
        "timeout_seconds": cfg.timeout_seconds,
        "transport": transport,
    }

    match cfg.provider:
        case "openai":
            return OpenAIVisionProvider(**common)  # type: ignore[arg-type]
        case "anthropic":
            return AnthropicVisionProvider(**common)  # type: ignore[arg-type]
        case "fake":
            return FakeVisionProvider(model=cfg.model)
        case "ollama":
            raise ConfigurationError(
                "Image captioning is not implemented for Ollama.",
                detail=(
                    "Set AXIS_VISION__PROVIDER=openai or =anthropic (with its own "
                    "AXIS_VISION__API_KEY) to caption images, or upload only PDF, "
                    "PPTX, and XLSX documents. The LLM provider can stay ollama — "
                    "the two are configured independently."
                ),
            )
        case unknown:
            raise ConfigurationError(
                f"AXIS_VISION__PROVIDER={unknown!r} is not a provider Axis knows.",
                detail="Supported values: openai, anthropic, fake.",
            )


def build_search_provider(settings: Settings) -> SearchProvider | None:
    """The agent's only route to the internet, or `None` if disabled.

    **Returning `None` rather than a no-op provider is load-bearing in two places.**
    The ReAct loop omits the web tool entirely when there is no provider, rather than
    offering the model a tool that silently returns nothing; and the Router leaves
    `WEB` out of its prompt, so it cannot route to a source that does not exist. A
    no-op provider would satisfy the type and break both — the model would confidently
    choose the web and find nothing, every time, with nothing in the trace saying why.

    `none` stays the default. Web search is opt-in because it costs money per call,
    reaches outside the student's own material, and carries the prompt-injection
    exposure System Design Section 6.5 records.
    """
    match settings.search.provider:
        case "none" | "":
            return None
        case "fake":
            return FakeSearchProvider()
        case "cached":
            # The class-demo provider: offline, deterministic, rehearsable.
            return CachedSearchProvider()
        case "serpapi":
            return SerpApiSearchProvider(
                api_key=(
                    settings.search.api_key.get_secret_value()
                    if settings.search.api_key
                    else None
                ),
                timeout_seconds=settings.search.timeout_seconds,
            )
        case unknown:
            raise ConfigurationError(
                f"AXIS_SEARCH__PROVIDER={unknown!r} is not a search provider Axis "
                f"knows.",
                detail=(
                    "Supported values: serpapi (live), cached (offline replay for a "
                    "class demo), fake (tests), none (no web route)."
                ),
            )


