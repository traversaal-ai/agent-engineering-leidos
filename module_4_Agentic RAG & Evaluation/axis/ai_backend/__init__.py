"""Axis AI Backend — pipelines, providers, retrievers, observability, evaluation.

This is the layer that knows *how* an answer is produced. The Backend dispatches
into it and gets an `Answer` back without learning anything about retrieval or
generation; the Frontend never imports it at all
(`tests/unit/test_layer_boundaries.py` enforces both).

Where to start reading, in this order:

    contracts/       the interfaces everything else codes against
    observability/   the @traced decorator and the AgentStep store
    providers/       swappable LLM/embedding adapters
    pipelines/       the two strategies Axis compares
"""

from ai_backend.config.settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
