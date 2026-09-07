"""Anthropic Messages API adapter.

Worth reading side by side with `openai_provider.py`: the two vendors differ in
three concrete ways, and each difference is absorbed here so that nothing
downstream ever branches on which provider is configured.

1. The system prompt is a top-level `system` field, not a message with
   `role: "system"`.
2. Content is a list of typed blocks, so text and tool calls arrive interleaved
   in one array rather than in separate fields.
3. `max_tokens` is required, not optional.

There is deliberately no `AnthropicEmbeddingProvider`: Anthropic publishes no
embeddings API. `registry.py` rejects that configuration at startup with an
explanation rather than letting it fail at the first query.
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from ai_backend.contracts.models import (
    Caption,
    Completion,
    CompletionChunk,
    FinishReason,
    Message,
    Role,
    StepType,
    ToolCall,
    ToolSpec,
)
from ai_backend.errors import ProviderError
from ai_backend.observability.trace import traced
from ai_backend.providers.base import (
    CAPTION_MAX_TOKENS,
    CAPTION_PROMPT,
    HttpProvider,
)

DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
API_VERSION = "2023-06-01"

# Anthropic's vocabulary for why generation stopped, mapped onto ours.
_STOP_REASONS = {
    "end_turn": FinishReason.STOP,
    "stop_sequence": FinishReason.STOP,
    "max_tokens": FinishReason.LENGTH,
    "tool_use": FinishReason.TOOL_CALLS,
    "refusal": FinishReason.CONTENT_FILTER,
}

# The API requires max_tokens on every request. This ceiling applies only when a
# caller passes none, and doubles as a cost guard: an unbounded completion is
# also an unbounded bill.
DEFAULT_MAX_TOKENS = 2048


class AnthropicLLMProvider(HttpProvider):
    name = "anthropic"

    def __init__(
        self,
        *,
        model: str = "claude-sonnet-5",
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
        headers["anthropic-version"] = API_VERSION
        if self._api_key:
            headers["x-api-key"] = self._api_key
        return headers

    @traced(StepType.GENERATE, label="anthropic.complete")
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
        system, conversation = _split_system(messages)

        payload: dict[str, Any] = {
            "model": target,
            "messages": conversation,
            "max_tokens": max_tokens or DEFAULT_MAX_TOKENS,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [_to_anthropic_tool(t) for t in tools]
        if temperature is not None:
            payload["temperature"] = temperature

        body = await self._post("/messages", payload)
        return self._parse_completion(body, target)

    def _parse_completion(self, body: dict[str, Any], model: str) -> Completion:
        blocks = body.get("content") or []
        if not isinstance(blocks, list):
            raise ProviderError("Anthropic returned an unexpected content shape.")

        # Text and tool_use blocks arrive interleaved in one array; flatten the
        # text and collect the tool calls separately for our Completion shape.
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text_parts.append(block.get("text") or "")
            elif block.get("type") == "tool_use":
                call = ToolCall(
                    name=block.get("name") or "",
                    arguments=block.get("input") or {},
                )
                if block.get("id"):
                    call = call.model_copy(update={"id": block["id"]})
                tool_calls.append(call)

        raw_usage = body.get("usage") or {}
        return Completion(
            text="".join(text_parts),
            model=body.get("model", model),
            usage=self._usage(
                prompt_tokens=int(raw_usage.get("input_tokens", 0)),
                completion_tokens=int(raw_usage.get("output_tokens", 0)),
                model=model,
            ),
            finish_reason=_STOP_REASONS.get(
                body.get("stop_reason") or "", FinishReason.OTHER
            ),
            tool_calls=tool_calls,
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
        system, conversation = _split_system(messages)
        payload: dict[str, Any] = {
            "model": target,
            "messages": conversation,
            "max_tokens": max_tokens or DEFAULT_MAX_TOKENS,
            "stream": True,
        }
        if system:
            payload["system"] = system
        if temperature is not None:
            payload["temperature"] = temperature

        url = f"{self._base_url}/messages"
        # Usage arrives split across two events: input tokens on message_start,
        # output tokens on message_delta. Carry the first until the second lands.
        prompt_tokens = 0

        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client, client.stream(
            "POST", url, json=payload, headers=self._headers()
        ) as response:
            if response.status_code >= 400:
                await response.aread()
                raise ProviderError(
                    f"Anthropic returned HTTP {response.status_code} for a "
                    f"streaming request.",
                    detail=response.text[:500],
                )
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:].strip())
                except ValueError:
                    continue

                kind = event.get("type")
                if kind == "message_start":
                    usage = (event.get("message") or {}).get("usage") or {}
                    prompt_tokens = int(usage.get("input_tokens", 0))
                elif kind == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        yield CompletionChunk(text=delta.get("text") or "")
                elif kind == "message_delta":
                    usage = event.get("usage") or {}
                    stop = (event.get("delta") or {}).get("stop_reason")
                    yield CompletionChunk(
                        finish_reason=_STOP_REASONS.get(
                            stop or "", FinishReason.OTHER
                        ),
                        usage=self._usage(
                            prompt_tokens=prompt_tokens,
                            completion_tokens=int(usage.get("output_tokens", 0)),
                            model=target,
                        ),
                    )
                elif kind == "message_stop":
                    return


class AnthropicVisionProvider(HttpProvider):
    """Image captioning via the Messages API with a base64 `image` block.

    A second vendor difference absorbed here rather than upstream: Anthropic takes
    the image as a typed `source` object with the media type named separately,
    where OpenAI takes a `data:` URI. Both produce the same `Caption`.
    """

    name = "anthropic"

    def __init__(
        self,
        *,
        model: str = "claude-sonnet-5",
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
        headers["anthropic-version"] = API_VERSION
        if self._api_key:
            headers["x-api-key"] = self._api_key
        return headers

    @traced(StepType.INGEST, label="anthropic.caption_image", capture_input=False)
    async def caption_image(
        self, image: bytes, *, mime_type: str, prompt: str | None = None
    ) -> Caption:
        body = await self._post(
            "/messages",
            {
                "model": self.model,
                "max_tokens": CAPTION_MAX_TOKENS,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": mime_type,
                                    "data": base64.b64encode(image).decode("ascii"),
                                },
                            },
                            {"type": "text", "text": prompt or CAPTION_PROMPT},
                        ],
                    }
                ],
            },
        )
        blocks = body.get("content") or []
        text = "".join(
            b.get("text") or ""
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        )
        raw_usage = body.get("usage") or {}
        return Caption(
            text=text,
            model=body.get("model", self.model),
            usage=self._usage(
                prompt_tokens=int(raw_usage.get("input_tokens", 0)),
                completion_tokens=int(raw_usage.get("output_tokens", 0)),
                model=self.model,
            ),
        )


def _split_system(messages: Sequence[Message]) -> tuple[str, list[dict[str, Any]]]:
    """Lift system messages out of the conversation.

    Anthropic takes the system prompt as a top-level field. Multiple system
    messages are joined rather than dropped, so a pipeline that layers two of
    them behaves the same on both vendors.
    """
    system_parts: list[str] = []
    conversation: list[dict[str, Any]] = []
    for message in messages:
        if message.role is Role.SYSTEM:
            system_parts.append(message.content)
        elif message.role is Role.TOOL:
            # A tool result is a user-role message carrying a tool_result block.
            conversation.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.tool_call_id or "",
                            "content": message.content,
                        }
                    ],
                }
            )
        elif message.tool_calls:
            # The assistant turn that requested tools, replayed as interleaved
            # text + tool_use blocks. Anthropic requires the `tool_use` block a
            # `tool_result` refers to, so the ReAct loop cannot feed a result back
            # without this.
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            blocks.extend(
                {
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": call.arguments,
                }
                for call in message.tool_calls
            )
            conversation.append({"role": str(message.role), "content": blocks})
        else:
            conversation.append({"role": str(message.role), "content": message.content})
    return "\n\n".join(system_parts), conversation


def _to_anthropic_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.parameters or {"type": "object", "properties": {}},
    }
