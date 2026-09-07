"""OpenAI chat and embedding adapters (Chat Completions + Embeddings)."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Sequence
from decimal import Decimal
from typing import Any

import httpx

from ai_backend.contracts.models import (
    Caption,
    Completion,
    CompletionChunk,
    EmbeddingResult,
    FinishReason,
    Message,
    Role,
    StepType,
    ToolCall,
    ToolSpec,
)
from ai_backend.errors import ProviderError
from ai_backend.observability.trace import traced
from ai_backend.providers import pricing
from ai_backend.providers.base import (
    CAPTION_MAX_TOKENS,
    CAPTION_PROMPT,
    HttpProvider,
    embedding_attributes,
)

_FINISH_REASONS = {
    "stop": FinishReason.STOP,
    "length": FinishReason.LENGTH,
    "tool_calls": FinishReason.TOOL_CALLS,
    "content_filter": FinishReason.CONTENT_FILTER,
}

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAILLMProvider(HttpProvider):
    name = "openai"

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
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

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    @traced(StepType.GENERATE, label="openai.complete")
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
        payload: dict[str, Any] = {
            "model": target,
            "messages": [_to_openai_message(m) for m in messages],
        }
        if tools:
            payload["tools"] = [_to_openai_tool(t) for t in tools]
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature

        body = await self._post("/chat/completions", payload)
        return self._parse_completion(body, target)

    def _parse_completion(self, body: dict[str, Any], model: str) -> Completion:
        choices = body.get("choices") or []
        if not choices:
            raise ProviderError("OpenAI returned no choices for a completion request.")
        choice = choices[0]
        message = choice.get("message") or {}

        raw_usage = body.get("usage") or {}
        prompt_tokens = int(raw_usage.get("prompt_tokens", 0))
        completion_tokens = int(raw_usage.get("completion_tokens", 0))

        return Completion(
            text=message.get("content") or "",
            model=body.get("model", model),
            usage=self._usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model=model,
            ),
            finish_reason=_FINISH_REASONS.get(
                choice.get("finish_reason") or "", FinishReason.OTHER
            ),
            tool_calls=[_from_openai_tool_call(tc) for tc in message.get("tool_calls") or []],
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
            "messages": [_to_openai_message(m) for m in messages],
            "stream": True,
            # Streaming responses omit usage unless explicitly requested, and
            # without it a streamed call would cost $0.00 in the trace.
            "stream_options": {"include_usage": True},
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if temperature is not None:
            payload["temperature"] = temperature

        async for chunk in self._stream_sse("/chat/completions", payload, target):
            yield chunk

    async def _stream_sse(
        self, path: str, payload: dict[str, Any], model: str
    ) -> AsyncIterator[CompletionChunk]:
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client, client.stream(
            "POST", url, json=payload, headers=self._headers()
        ) as response:
            if response.status_code >= 400:
                await response.aread()
                raise ProviderError(
                    f"OpenAI returned HTTP {response.status_code} for a "
                    f"streaming request.",
                    detail=response.text[:500],
                )
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    event = json.loads(data)
                except ValueError:
                    continue
                yield self._parse_chunk(event, model)

    def _parse_chunk(self, event: dict[str, Any], model: str) -> CompletionChunk:
        choices = event.get("choices") or []
        delta = (choices[0].get("delta") or {}) if choices else {}
        finish = choices[0].get("finish_reason") if choices else None
        raw_usage = event.get("usage")
        return CompletionChunk(
            text=delta.get("content") or "",
            finish_reason=_FINISH_REASONS.get(finish or "") if finish else None,
            usage=(
                self._usage(
                    prompt_tokens=int(raw_usage.get("prompt_tokens", 0)),
                    completion_tokens=int(raw_usage.get("completion_tokens", 0)),
                    model=model,
                )
                if raw_usage
                else None
            ),
        )


class OpenAIVisionProvider(HttpProvider):
    """Image captioning via Chat Completions with an `image_url` content block.

    OpenAI accepts an inline image as a `data:` URI in the message content array.
    Note this uses the same chat endpoint as `OpenAILLMProvider` — the difference
    is entirely in the payload shape, which is why captioning does not need
    `Message` to grow an image variant.
    """

    name = "openai"

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
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

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    # The image bytes are not captured into the trace — only the caption. A
    # base64 data URI of a slide would be hundreds of kilobytes of noise.
    @traced(StepType.INGEST, label="openai.caption_image", capture_input=False)
    async def caption_image(
        self, image: bytes, *, mime_type: str, prompt: str | None = None
    ) -> Caption:
        data_uri = f"data:{mime_type};base64,{base64.b64encode(image).decode('ascii')}"
        body = await self._post(
            "/chat/completions",
            {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt or CAPTION_PROMPT},
                            {"type": "image_url", "image_url": {"url": data_uri}},
                        ],
                    }
                ],
                "max_tokens": CAPTION_MAX_TOKENS,
            },
        )
        choices = body.get("choices") or []
        if not choices:
            raise ProviderError("OpenAI returned no choices for an image caption.")
        raw_usage = body.get("usage") or {}
        return Caption(
            text=(choices[0].get("message") or {}).get("content") or "",
            model=body.get("model", self.model),
            usage=self._usage(
                prompt_tokens=int(raw_usage.get("prompt_tokens", 0)),
                completion_tokens=int(raw_usage.get("completion_tokens", 0)),
                model=self.model,
            ),
        )


class OpenAIEmbeddingProvider(HttpProvider):
    name = "openai"

    # Kept here rather than probed at runtime: Chroma needs the dimensionality
    # when a collection is created, before any embedding call has happened.
    _DIMENSIONS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
    }

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url or DEFAULT_BASE_URL,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )
        self.dimensions = self._DIMENSIONS.get(model, 1536)

    def _headers(self) -> dict[str, str]:
        headers = super()._headers()
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    # Vectors are not captured: a few thousand floats per call would drown the
    # trace view and teach nothing. Token count and cost still land on the step.
    # `capture_output=False` still: the full vectors never reach the store. What
    # `attributes_from` adds is the width and the first few numbers, which is what
    # makes "text becomes a vector" something a student can see rather than be told.
    @traced(
        StepType.EMBED,
        label="openai.embed",
        capture_output=False,
        attributes_from=embedding_attributes,
    )
    async def embed(
        self, texts: Sequence[str], *, model: str | None = None
    ) -> EmbeddingResult:
        target = model or self.model
        body = await self._post(
            "/embeddings", {"model": target, "input": list(texts)}
        )
        data = body.get("data") or []
        raw_usage = body.get("usage") or {}
        return EmbeddingResult(
            vectors=[list(item.get("embedding") or []) for item in data],
            model=body.get("model", target),
            usage=self._usage(
                prompt_tokens=int(raw_usage.get("prompt_tokens", 0)),
                completion_tokens=0,
                model=target,
            ),
        )

    def estimate_cost(
        self, *, prompt_tokens: int, model: str | None = None, **_: object
    ) -> Decimal:
        return pricing.cost_of(model=model or self.model, prompt_tokens=prompt_tokens)


def _to_openai_message(message: Message) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": str(message.role), "content": message.content}
    if message.role is Role.TOOL and message.tool_call_id:
        payload["tool_call_id"] = message.tool_call_id
    if message.name:
        payload["name"] = message.name
    if message.tool_calls:
        # Replaying the assistant turn that requested tools. The API rejects a
        # `tool` message whose `tool_call_id` matches no preceding call, so the
        # ReAct loop cannot feed a result back without this.
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments),
                },
            }
            for call in message.tool_calls
        ]
        # `content` must be null, not "", on an assistant turn that only calls tools.
        if not message.content:
            payload["content"] = None
    return payload


def _to_openai_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters or {"type": "object", "properties": {}},
        },
    }


def _from_openai_tool_call(raw: dict[str, Any]) -> ToolCall:
    function = raw.get("function") or {}
    raw_args = function.get("arguments") or "{}"
    try:
        arguments = json.loads(raw_args)
    except ValueError:
        # A model can emit malformed JSON arguments. Preserving the raw string
        # rather than raising keeps the failure visible in the trace, which is
        # what Section 11 asks for — the agent loop can then decide to retry.
        arguments = {"_unparsed": raw_args}
    call = ToolCall(
        name=function.get("name") or "",
        arguments=arguments if isinstance(arguments, dict) else {"_value": arguments},
    )
    # Keep the vendor's id when there is one: tool results must be correlated
    # back to the call that requested them across a multi-turn ReAct loop.
    if raw.get("id"):
        call = call.model_copy(update={"id": raw["id"]})
    return call
