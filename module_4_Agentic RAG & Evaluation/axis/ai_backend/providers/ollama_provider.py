"""Ollama adapters — the zero-API-key path.

This is the provider that makes Axis usable on a laptop with no budget and no
keys, which matters for two of the PRD's constraints at once: the single-machine
reliability criterion, and a workshop whose per-student budget has not been
approved yet.

One thing to say out loud in class: local models are priced at $0.00 in
`pricing.py`, which is honest at the API boundary but makes the cost column of a
Compare run meaningless. The compute is real, it is just being paid for in laptop
fan noise rather than dollars. Comparing a local run's cost against a cloud run's
is the one comparison this platform cannot make.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from decimal import Decimal
from typing import Any

import httpx

from ai_backend.contracts.models import (
    Completion,
    CompletionChunk,
    EmbeddingResult,
    FinishReason,
    Message,
    StepType,
    ToolSpec,
)
from ai_backend.observability.trace import traced
from ai_backend.providers import pricing
from ai_backend.providers.base import HttpProvider, embedding_attributes

DEFAULT_BASE_URL = "http://127.0.0.1:11434"


class OllamaLLMProvider(HttpProvider):
    name = "ollama"

    def __init__(
        self,
        *,
        model: str = "llama3.1",
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # A generous default timeout: a local model on CPU is slow, and a
        # spurious timeout mid-demo is worse than a slow answer.
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url or DEFAULT_BASE_URL,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )

    @traced(StepType.GENERATE, label="ollama.complete")
    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
        tools: Sequence[ToolSpec] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Completion:
        target = model or self.model
        options: dict[str, Any] = {}
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        if temperature is not None:
            options["temperature"] = temperature

        payload: dict[str, Any] = {
            "model": target,
            "messages": [{"role": str(m.role), "content": m.content} for m in messages],
            "stream": False,
        }
        if options:
            payload["options"] = options

        body = await self._post("/api/chat", payload)
        message = body.get("message") or {}
        return Completion(
            text=message.get("content") or "",
            model=body.get("model", target),
            usage=self._usage(
                prompt_tokens=int(body.get("prompt_eval_count", 0)),
                completion_tokens=int(body.get("eval_count", 0)),
                model=target,
            ),
            finish_reason=(
                FinishReason.STOP if body.get("done") else FinishReason.LENGTH
            ),
        )

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[CompletionChunk]:
        target = model or self.model
        payload: dict[str, Any] = {
            "model": target,
            "messages": [{"role": str(m.role), "content": m.content} for m in messages],
            "stream": True,
        }
        url = f"{self._base_url}/api/chat"
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client, client.stream(
            "POST", url, json=payload, headers=self._headers()
        ) as response:
            response.raise_for_status()
            # Ollama streams newline-delimited JSON, not SSE — no `data:`
            # prefix and no [DONE] sentinel.
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("done"):
                    yield CompletionChunk(
                        finish_reason=FinishReason.STOP,
                        usage=self._usage(
                            prompt_tokens=int(event.get("prompt_eval_count", 0)),
                            completion_tokens=int(event.get("eval_count", 0)),
                            model=target,
                        ),
                    )
                    return
                yield CompletionChunk(
                    text=(event.get("message") or {}).get("content") or ""
                )


class OllamaEmbeddingProvider(HttpProvider):
    name = "ollama"

    _DIMENSIONS = {"nomic-embed-text": 768, "mxbai-embed-large": 1024}

    def __init__(
        self,
        *,
        model: str = "nomic-embed-text",
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url or DEFAULT_BASE_URL,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )
        self.dimensions = self._DIMENSIONS.get(model, 768)

    @traced(
        StepType.EMBED,
        label="ollama.embed",
        capture_output=False,
        attributes_from=embedding_attributes,
    )
    async def embed(
        self, texts: Sequence[str], *, model: str | None = None
    ) -> EmbeddingResult:
        target = model or self.model
        body = await self._post("/api/embed", {"model": target, "input": list(texts)})
        vectors = body.get("embeddings") or []
        return EmbeddingResult(
            vectors=[list(v) for v in vectors],
            model=target,
            usage=self._usage(
                prompt_tokens=int(body.get("prompt_eval_count", 0)),
                completion_tokens=0,
                model=target,
            ),
        )

    def estimate_cost(
        self, *, prompt_tokens: int, model: str | None = None, **_: object
    ) -> Decimal:
        return pricing.cost_of(model=model or self.model, prompt_tokens=prompt_tokens)
