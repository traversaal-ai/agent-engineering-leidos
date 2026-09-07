"""Stable interfaces and data shapes for Axis.

This package is the one every other layer imports and nothing in it imports back.
It is held to a stricter type-checking standard than the rest of the tree (see
`[[tool.mypy.overrides]]` in pyproject.toml), because it doubles as the reference
a student reads after the course to reuse the pattern in their own project.
"""

from ai_backend.contracts.models import (
    EMPTY_USAGE,
    AgentStep,
    Answer,
    Caption,
    Chunk,
    Citation,
    Completion,
    CompletionChunk,
    Document,
    EmbeddingResult,
    FinishReason,
    IngestionResult,
    Message,
    Modality,
    RetrievedContext,
    Role,
    StepStatus,
    StepType,
    Strategy,
    ToolCall,
    ToolSpec,
    Usage,
    new_id,
    utc_now,
)
from ai_backend.contracts.pipeline import Pipeline, QueryBudget, QueryContext
from ai_backend.contracts.providers import (
    EmbeddingProvider,
    LLMProvider,
    SearchProvider,
    VisionProvider,
)
from ai_backend.contracts.retriever import Retriever

__all__ = [
    "EMPTY_USAGE",
    "AgentStep",
    "Answer",
    "Caption",
    "Chunk",
    "Citation",
    "Completion",
    "CompletionChunk",
    "Document",
    "EmbeddingProvider",
    "EmbeddingResult",
    "FinishReason",
    "IngestionResult",
    "LLMProvider",
    "Message",
    "Modality",
    "Pipeline",
    "QueryBudget",
    "QueryContext",
    "RetrievedContext",
    "Retriever",
    "Role",
    "SearchProvider",
    "StepStatus",
    "StepType",
    "Strategy",
    "ToolCall",
    "ToolSpec",
    "Usage",
    "VisionProvider",
    "new_id",
    "utc_now",
]
