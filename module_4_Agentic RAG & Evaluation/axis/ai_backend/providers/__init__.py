"""Swappable LLM, embedding, and search adapters.

Built on raw `httpx` rather than vendor SDKs — the reasoning is in `base.py`.
Construct them through `registry.py`, never directly from a pipeline: the
registry is the only place a provider name appears as a string, which is what
keeps pipelines provider-agnostic.
"""

from ai_backend.providers.registry import (
    build_embedding_provider,
    build_llm_provider,
    build_search_provider,
    build_vision_provider,
)

__all__ = [
    "build_embedding_provider",
    "build_llm_provider",
    "build_search_provider",
    "build_vision_provider",
]
