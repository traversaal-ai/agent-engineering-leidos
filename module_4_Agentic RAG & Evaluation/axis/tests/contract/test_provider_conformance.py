"""One suite, every provider.

CLAUDE.md requires providers be swappable and forbids hardcoding one inside a
pipeline. "Swappable" is only true if the implementations genuinely behave alike,
so the same tests run against OpenAI, Anthropic, Ollama, and the fake, with
`respx` standing in for the network.

This is the payoff for writing the adapters over raw `httpx` rather than vendor
SDKs: one mocking approach covers all three real providers identically. With
three different SDKs, this file would need three different fakes and would stop
being a conformance suite.

No API keys and no network — the autouse fixture in `conftest.py` fails any real
socket.
"""

from __future__ import annotations

import json
import tempfile
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from ai_backend.contracts.models import (
    Completion,
    FinishReason,
    Message,
    Role,
    SearchResult,
    StepType,
    ToolCall,
    ToolSpec,
)
from ai_backend.contracts.providers import EmbeddingProvider, LLMProvider
from ai_backend.errors import ConfigurationError, ProviderError
from ai_backend.observability import InMemoryStepStore, trace_context
from ai_backend.observability import trace as trace_module
from ai_backend.providers.anthropic_provider import AnthropicLLMProvider
from ai_backend.providers.fake import (
    FakeEmbeddingProvider,
    FakeLLMProvider,
    FakeSearchProvider,
)
from ai_backend.providers.ollama_provider import OllamaEmbeddingProvider, OllamaLLMProvider
from ai_backend.providers.openai_provider import OpenAIEmbeddingProvider, OpenAILLMProvider
from ai_backend.providers.search import CachedSearchProvider, SerpApiSearchProvider

QUESTION = [Message(role=Role.USER, content="How long is parental leave?")]


@pytest.fixture(autouse=True)
def _traced(monkeypatch: pytest.MonkeyPatch):
    """Provider methods are `@traced`, so they need an active trace context."""
    store = InMemoryStepStore()
    previous = trace_module.get_store()
    trace_module.configure(store=store)
    with trace_context(session_id="s1", trace_id="t1"):
        yield store
    trace_module.configure(store=previous)


# ---------------------------------------------------------------------------
# Canned vendor responses. Each is the real wire shape for that provider — the
# differences between them are exactly what the adapters exist to absorb.
# ---------------------------------------------------------------------------

_OPENAI_BODY = {
    "model": "gpt-4o-mini",
    "choices": [
        {
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "Sixteen weeks."},
        }
    ],
    "usage": {"prompt_tokens": 42, "completion_tokens": 8},
}

_ANTHROPIC_BODY = {
    "model": "claude-sonnet-5",
    "stop_reason": "end_turn",
    # Note the shape difference: a list of typed blocks, not a `message.content`.
    "content": [{"type": "text", "text": "Sixteen weeks."}],
    "usage": {"input_tokens": 42, "output_tokens": 8},
}

_OLLAMA_BODY = {
    "model": "llama3.1",
    "done": True,
    "message": {"role": "assistant", "content": "Sixteen weeks."},
    "prompt_eval_count": 42,
    "eval_count": 8,
}


def _llm_cases():
    return [
        pytest.param(
            OpenAILLMProvider(model="gpt-4o-mini", api_key="sk-test"),
            "https://api.openai.com/v1/chat/completions",
            _OPENAI_BODY,
            id="openai",
        ),
        pytest.param(
            AnthropicLLMProvider(model="claude-sonnet-5", api_key="sk-ant-test"),
            "https://api.anthropic.com/v1/messages",
            _ANTHROPIC_BODY,
            id="anthropic",
        ),
        pytest.param(
            OllamaLLMProvider(model="llama3.1"),
            "http://127.0.0.1:11434/api/chat",
            _OLLAMA_BODY,
            id="ollama",
        ),
    ]


# ---------------------------------------------------------------------------
# The shared contract.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider,url,body", _llm_cases())
@respx.mock
async def test_every_llm_provider_returns_the_same_completion_shape(
    provider: LLMProvider, url: str, body: dict
) -> None:
    """Three wire formats in, one `Completion` out. That is the whole point."""
    respx.post(url).mock(return_value=httpx.Response(200, json=body))

    completion = await provider.complete(QUESTION)

    assert isinstance(completion, Completion)
    assert completion.text == "Sixteen weeks."
    assert completion.finish_reason is FinishReason.STOP
    assert completion.usage.prompt_tokens == 42
    assert completion.usage.completion_tokens == 8


@pytest.mark.parametrize("provider,url,body", _llm_cases())
@respx.mock
async def test_cost_is_computed_by_axis_not_read_from_the_vendor(
    provider: LLMProvider, url: str, body: dict
) -> None:
    """None of the canned responses contains a price, yet each reports a cost.

    Vendors report token usage, not dollars. Axis prices its own calls from
    `pricing.py`, which is what makes the per-session cap trustworthy.
    """
    respx.post(url).mock(return_value=httpx.Response(200, json=body))

    completion = await provider.complete(QUESTION)

    assert isinstance(completion.usage.cost_usd, Decimal)
    # Ollama is legitimately free; the cloud providers are not.
    if provider.name == "ollama":
        assert completion.usage.cost_usd == 0
    else:
        assert completion.usage.cost_usd > 0


@pytest.mark.parametrize("provider,url,body", _llm_cases())
@respx.mock
async def test_every_llm_call_emits_exactly_one_trace_step(
    provider: LLMProvider, url: str, body: dict, _traced: InMemoryStepStore
) -> None:
    """Uniform instrumentation is what makes the two strategies comparable.

    A provider that forgot to be traced would report zero cost and appear to win
    every comparison.
    """
    respx.post(url).mock(return_value=httpx.Response(200, json=body))

    await provider.complete(QUESTION)

    steps = [s for s in _traced.all_steps if s.step_type.value == "generate"]
    assert len(steps) == 1, [s.label for s in _traced.all_steps]
    assert steps[0].usage.prompt_tokens == 42


@pytest.mark.parametrize("provider,url,body", _llm_cases())
def test_every_llm_provider_can_estimate_before_calling(
    provider: LLMProvider, url: str, body: dict
) -> None:
    """The method the cost cap depends on.

    The estimate must price the completion at its full permitted length —
    pessimistic is the only safe direction when the number decides whether to
    spend a shared budget.
    """
    small = provider.estimate_cost(prompt_tokens=100, max_completion_tokens=100)
    large = provider.estimate_cost(prompt_tokens=100, max_completion_tokens=10_000)

    assert isinstance(small, Decimal)
    if provider.name != "ollama":
        assert large > small, "a longer permitted completion must estimate higher"


@pytest.mark.parametrize("provider,url,body", _llm_cases())
def test_every_llm_provider_counts_tokens(
    provider: LLMProvider, url: str, body: dict
) -> None:
    assert provider.count_tokens("") == 0
    assert provider.count_tokens("a longer piece of text") > 0


@pytest.mark.parametrize("provider,url,body", _llm_cases())
@respx.mock
async def test_a_rate_limit_is_its_own_error_type(
    provider: LLMProvider, url: str, body: dict
) -> None:
    """PRD Section 7 flags a whole classroom hitting one provider at once.

    A distinct type so the student-facing message can say "busy, try again"
    rather than "broken".
    """
    from ai_backend.errors import ProviderRateLimitError

    respx.post(url).mock(return_value=httpx.Response(429, json={"error": "slow down"}))

    with pytest.raises(ProviderRateLimitError):
        await provider.complete(QUESTION)


@pytest.mark.parametrize("provider,url,body", _llm_cases())
@respx.mock
async def test_an_upstream_error_becomes_a_provider_error(
    provider: LLMProvider, url: str, body: dict
) -> None:
    """No vendor exception types leak past the adapter.

    Otherwise every pipeline would have to know which provider it holds in order
    to catch anything.
    """
    from ai_backend.errors import ProviderError

    respx.post(url).mock(return_value=httpx.Response(500, text="internal"))

    with pytest.raises(ProviderError):
        await provider.complete(QUESTION)


@pytest.mark.parametrize("provider,url,body", _llm_cases())
@respx.mock
async def test_a_failed_call_still_leaves_a_trace_step(
    provider: LLMProvider, url: str, body: dict, _traced: InMemoryStepStore
) -> None:
    """Section 11: failures must be visible, including provider failures."""
    from ai_backend.errors import ProviderError

    respx.post(url).mock(return_value=httpx.Response(500, text="internal"))

    with pytest.raises(ProviderError):
        await provider.complete(QUESTION)

    assert any(s.status.value == "error" for s in _traced.all_steps)


# ---------------------------------------------------------------------------
# Tool calling — the shape Milestone 1's ReAct loop depends on.
# ---------------------------------------------------------------------------


@respx.mock
async def test_openai_tool_calls_are_translated_to_the_neutral_shape() -> None:
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {
                                        "name": "web_search",
                                        "arguments": '{"query": "parental leave"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    provider = OpenAILLMProvider(model="gpt-4o-mini", api_key="sk-test")

    completion = await provider.complete(
        QUESTION, tools=[ToolSpec(name="web_search", description="search")]
    )

    assert completion.finish_reason is FinishReason.TOOL_CALLS
    (call,) = completion.tool_calls
    assert call.id == "call_1"
    assert call.name == "web_search"
    assert call.arguments == {"query": "parental leave"}


@respx.mock
async def test_anthropic_tool_calls_are_translated_to_the_same_shape() -> None:
    """The same `ToolCall` out of a completely different wire format.

    Anthropic interleaves `tool_use` blocks with text in one content array. If
    this translation lived in the ReAct loop instead of here, the loop would need
    a branch per vendor — which CLAUDE.md forbids and which would make Milestone 3
    a rewrite instead of a swap.
    """
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "claude-sonnet-5",
                "stop_reason": "tool_use",
                "content": [
                    {"type": "text", "text": "Let me look that up."},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "web_search",
                        "input": {"query": "parental leave"},
                    },
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )
    )
    provider = AnthropicLLMProvider(model="claude-sonnet-5", api_key="sk-ant-test")

    completion = await provider.complete(
        QUESTION, tools=[ToolSpec(name="web_search", description="search")]
    )

    assert completion.finish_reason is FinishReason.TOOL_CALLS
    (call,) = completion.tool_calls
    assert call.id == "toolu_1"
    assert call.name == "web_search"
    assert call.arguments == {"query": "parental leave"}
    # Text alongside the tool call is preserved, not discarded.
    assert "look that up" in completion.text


# ---------------------------------------------------------------------------
# Replaying a tool exchange — the *second* turn of the ReAct loop.
#
# Getting a tool call back is only half of tool calling. Feeding the result in
# requires sending the assistant turn that requested it, and both vendors reject a
# tool result that stands alone: OpenAI 400s on a `tool_call_id` matching no prior
# call, Anthropic on a `tool_result` with no `tool_use`.
#
# These tests exist because that failure is invisible offline. The fake provider
# ignores the message list entirely, so a loop that sent only the result would pass
# every acceptance test and break against a real key — the same shape as two defects
# already found by running the app rather than the suite.
# ---------------------------------------------------------------------------


def _tool_exchange() -> list[Message]:
    call = ToolCall(id="call_1", name="search_documents", arguments={"query": "leave"})
    return [
        Message(role=Role.USER, content="How long is parental leave?"),
        Message(role=Role.ASSISTANT, content="", tool_calls=[call]),
        Message(
            role=Role.TOOL,
            content="Found 1 passage: 16 weeks.",
            tool_call_id=call.id,
            name=call.name,
        ),
    ]


@respx.mock
async def test_openai_replays_the_assistant_turn_that_requested_a_tool() -> None:
    route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini",
                "choices": [
                    {"finish_reason": "stop", "message": {"role": "assistant", "content": "16 weeks."}}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
    )
    provider = OpenAILLMProvider(model="gpt-4o-mini", api_key="sk-test")

    await provider.complete(_tool_exchange())

    sent = json.loads(route.calls.last.request.content)["messages"]
    assistant = next(m for m in sent if m["role"] == "assistant")
    (call,) = assistant["tool_calls"]
    assert call["id"] == "call_1"
    assert call["type"] == "function"
    assert call["function"]["name"] == "search_documents"
    # Arguments go over the wire as a JSON *string*, not an object.
    assert json.loads(call["function"]["arguments"]) == {"query": "leave"}
    # An assistant turn that only calls tools must send null content, not "".
    assert assistant["content"] is None

    tool = next(m for m in sent if m["role"] == "tool")
    assert tool["tool_call_id"] == "call_1"


@respx.mock
async def test_anthropic_replays_the_assistant_turn_that_requested_a_tool() -> None:
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "claude-sonnet-5",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "16 weeks."}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )
    )
    provider = AnthropicLLMProvider(model="claude-sonnet-5", api_key="sk-ant-test")

    await provider.complete(_tool_exchange())

    sent = json.loads(route.calls.last.request.content)["messages"]
    assistant = next(m for m in sent if m["role"] == "assistant")
    (block,) = assistant["content"]
    assert block["type"] == "tool_use"
    assert block["id"] == "call_1"
    assert block["name"] == "search_documents"
    # Anthropic takes the arguments as an object, where OpenAI takes a string.
    assert block["input"] == {"query": "leave"}

    result_turn = sent[-1]
    assert result_turn["role"] == "user"
    assert result_turn["content"][0]["tool_use_id"] == "call_1"


@respx.mock
async def test_anthropic_lifts_the_system_prompt_out_of_the_messages() -> None:
    """A vendor difference absorbed entirely inside the adapter."""
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json=_ANTHROPIC_BODY)
    )
    provider = AnthropicLLMProvider(model="claude-sonnet-5", api_key="sk-ant-test")

    await provider.complete(
        [
            Message(role=Role.SYSTEM, content="You are precise."),
            Message(role=Role.USER, content="How long is leave?"),
        ]
    )

    sent = route.calls.last.request
    import json

    payload = json.loads(sent.content)
    assert payload["system"] == "You are precise."
    assert [m["role"] for m in payload["messages"]] == ["user"]


@pytest.mark.parametrize(
    "model,accepted",
    [
        ("claude-sonnet-5", False),
        ("claude-opus-5", False),
        ("claude-opus-4-8", False),
        ("claude-opus-4-7", False),
        ("claude-fable-5-1", False),
        ("claude-mythos-5-1", False),
        ("claude-opus-4-6", True),
        ("claude-sonnet-4-6", True),
        ("claude-haiku-4-5", True),
    ],
)
def test_the_temperature_cut_is_at_the_models_that_reject_it(
    model: str, accepted: bool
) -> None:
    """Which models still take `temperature`, pinned on both sides of the line.

    Anthropic removed the sampling parameters as of Opus 4.7 and answers a request
    carrying one with HTTP 400 rather than ignoring it — so with `temperature=0.0`
    hardcoded in both pipelines, every call on such a model failed outright. The first
    fix listed the three Claude 5 ids, which is where the 400 had been met, and left
    `claude-opus-4-8` and `claude-opus-4-7` failing exactly as `claude-sonnet-5` had.

    Kept where it is honoured, because Axis asks for 0.0 deliberately: a demo that
    answers differently on a re-run of the same question makes the two strategies look
    like they differ when only the sampling did.
    """
    from ai_backend.providers.anthropic_provider import _accepts_temperature

    assert _accepts_temperature(model) is accepted


@respx.mock
async def test_anthropic_does_not_put_temperature_on_the_wire_for_claude_5() -> None:
    """And the check is actually wired into the request, not just available."""
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json=_ANTHROPIC_BODY)
    )
    provider = AnthropicLLMProvider(model="claude-sonnet-5", api_key="sk-ant-test")

    await provider.complete(
        [Message(role=Role.USER, content="How long is leave?")], temperature=0.0
    )

    assert "temperature" not in json.loads(route.calls.last.request.content)


@respx.mock
async def test_anthropic_still_sends_temperature_where_it_is_honoured() -> None:
    """The other half: dropping it everywhere would cost the demo its determinism."""
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json=_ANTHROPIC_BODY)
    )
    provider = AnthropicLLMProvider(
        model="claude-haiku-4-5-20251001", api_key="sk-ant-test"
    )

    await provider.complete(
        [Message(role=Role.USER, content="How long is leave?")], temperature=0.0
    )

    assert json.loads(route.calls.last.request.content)["temperature"] == 0.0


# ---------------------------------------------------------------------------
# Embedding providers.
# ---------------------------------------------------------------------------


def _embedding_cases():
    return [
        pytest.param(
            OpenAIEmbeddingProvider(model="text-embedding-3-small", api_key="sk-test"),
            "https://api.openai.com/v1/embeddings",
            {
                "model": "text-embedding-3-small",
                "data": [{"embedding": [0.1, 0.2, 0.3]}, {"embedding": [0.4, 0.5, 0.6]}],
                "usage": {"prompt_tokens": 12},
            },
            id="openai",
        ),
        pytest.param(
            OllamaEmbeddingProvider(model="nomic-embed-text"),
            "http://127.0.0.1:11434/api/embed",
            {
                "embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
                "prompt_eval_count": 12,
            },
            id="ollama",
        ),
    ]


@pytest.mark.parametrize("provider,url,body", _embedding_cases())
@respx.mock
async def test_every_embedding_provider_returns_one_vector_per_text(
    provider: EmbeddingProvider, url: str, body: dict
) -> None:
    respx.post(url).mock(return_value=httpx.Response(200, json=body))

    result = await provider.embed(["first", "second"])

    assert len(result.vectors) == 2
    assert result.vectors[0] == [0.1, 0.2, 0.3]


@pytest.mark.parametrize("provider,url,body", _embedding_cases())
def test_every_embedding_provider_declares_its_dimensions(
    provider: EmbeddingProvider, url: str, body: dict
) -> None:
    """Chroma needs this when a collection is created, before any embedding call."""
    assert provider.dimensions > 0


@pytest.mark.parametrize("provider,url,body", _embedding_cases())
@respx.mock
async def test_embedding_vectors_are_not_written_into_the_trace(
    provider: EmbeddingProvider, url: str, body: dict, _traced: InMemoryStepStore
) -> None:
    """A few thousand floats per call would drown the trace view.

    Cost and token count still land on the step, which is what the comparison
    needs.
    """
    respx.post(url).mock(return_value=httpx.Response(200, json=body))

    await provider.embed(["first"])

    steps = [s for s in _traced.all_steps if s.step_type.value == "embed"]
    assert steps
    assert steps[0].raw_output is None
    assert steps[0].usage.prompt_tokens == 12


# ---------------------------------------------------------------------------
# The fake providers satisfy the same contract — which is what makes them a
# legitimate stand-in throughout the suite rather than a convenient shortcut.
# ---------------------------------------------------------------------------


def test_the_fakes_satisfy_the_protocols() -> None:
    assert isinstance(FakeLLMProvider(), LLMProvider)
    assert isinstance(FakeEmbeddingProvider(), EmbeddingProvider)


def test_the_real_providers_satisfy_the_protocols() -> None:
    """Structural typing, checked. `Protocol` conformance is otherwise invisible
    until something fails at runtime.
    """
    for provider in (
        OpenAILLMProvider(api_key="sk-test"),
        AnthropicLLMProvider(api_key="sk-ant-test"),
        OllamaLLMProvider(),
    ):
        assert isinstance(provider, LLMProvider), provider.name

    for embedder in (OpenAIEmbeddingProvider(api_key="sk-test"), OllamaEmbeddingProvider()):
        assert isinstance(embedder, EmbeddingProvider), embedder.name


async def test_the_fake_llm_is_deterministic(_traced) -> None:
    """PRD Section 7 lists non-determinism as a live risk.

    The suite must not inherit it, so the same script always produces the same
    answer.
    """
    first = FakeLLMProvider(responses=["alpha", "beta"])
    second = FakeLLMProvider(responses=["alpha", "beta"])

    assert (await first.complete(QUESTION)).text == (await second.complete(QUESTION)).text


async def test_the_fake_llm_counts_its_calls(_traced) -> None:
    """The observable behind every "no LLM call was made" assertion in the suite."""
    provider = FakeLLMProvider()

    assert provider.call_count == 0
    await provider.complete(QUESTION)
    assert provider.call_count == 1


async def test_the_fake_embedding_is_content_derived(_traced) -> None:
    """Same text embeds identically; different text differs.

    Enough for a retrieval test to assert the right chunk came back, with no model
    involved.
    """
    provider = FakeEmbeddingProvider()

    result = await provider.embed(["same", "same", "different"])

    assert result.vectors[0] == result.vectors[1]
    assert result.vectors[0] != result.vectors[2]


# ---------------------------------------------------------------------------
# Search providers
# ---------------------------------------------------------------------------
#
# Held to the same bar as the LLM adapters: one shape out, cost computed by Axis,
# one trace step per call. The extra property here is a *negative* one — the
# interface must offer no way to fetch a URL, which is the SSRF control in System
# Design Section 6.5 expressed as an absence rather than as a validation rule.


def test_no_search_provider_offers_a_way_to_fetch_a_url() -> None:
    """The SSRF boundary, asserted structurally.

    A result's `url` is data to show a student, never an address to request. This
    would be a one-line convenience to add and a security regression to ship, and a
    prose rule in a docstring is exactly the kind that erodes — so the absence is a
    test.
    """
    for provider in (FakeSearchProvider(), _cached_provider()):
        for forbidden in ("fetch", "get", "open_url", "retrieve_url", "download"):
            assert not hasattr(provider, forbidden), (
                f"{provider.name} exposes {forbidden!r}; the search interface must "
                f"offer no way to request a URL"
            )


def _cached_provider(tmp: Path | None = None) -> CachedSearchProvider:
    """A cached provider over a throwaway recording.

    Written to a temp directory rather than pointed at the committed cache, so this
    suite does not depend on what an instructor happened to record.
    """
    directory = tmp or Path(tempfile.mkdtemp())
    (directory / "demo.json").write_text(
        json.dumps(
            {
                "newest models": [
                    {"title": "A page", "url": "https://example.test/a", "snippet": "Text."}
                ]
            }
        ),
        encoding="utf-8",
    )
    return CachedSearchProvider(cache_dir=directory)


async def test_every_search_provider_returns_the_same_result_shape(_traced) -> None:
    for provider in (FakeSearchProvider(), _cached_provider()):
        result = await provider.search("newest models")

        assert isinstance(result, SearchResult), provider.name
        assert result.sources, provider.name
        assert all(s.snippet for s in result.sources), provider.name


async def test_a_search_costs_what_axis_says_it_costs(_traced) -> None:
    """Priced by Axis per *call*, not read from a vendor and not per token.

    A search API charges the same for a three-word query as a thirty-word one, so a
    per-MTok rate would round to nothing and the cap would be unlimited along this
    axis while every check passed.
    """
    provider = FakeSearchProvider()

    estimate = provider.estimate_cost()
    result = await provider.search("anything")

    assert estimate > 0
    assert result.usage.cost_usd == estimate
    assert result.usage.prompt_tokens == 0


async def test_every_search_call_emits_exactly_one_trace_step(_traced) -> None:
    await FakeSearchProvider().search("anything")

    search_steps = [
        s for s in _traced.all_steps if s.step_type is StepType.SEARCH_WEB
    ]
    assert len(search_steps) == 1
    assert search_steps[0].usage.cost_usd > 0


async def test_a_cached_miss_returns_nothing_rather_than_going_live(_traced) -> None:
    """A query with no recording must not fall through to a network call.

    A silent live fallback would make the demo network-dependent again at exactly the
    moment nobody was watching for it. "No results" is a state the pipeline already
    renders visibly.
    """
    result = await _cached_provider().search("a query nobody recorded")

    assert result.sources == []


def test_a_cached_provider_with_no_recordings_refuses_to_start() -> None:
    """Loudly, during prep, rather than silently in the room.

    An empty cache would look configured and return nothing for every query — the
    exact failure this provider exists to prevent.
    """
    with pytest.raises(ConfigurationError):
        CachedSearchProvider(cache_dir=Path(tempfile.mkdtemp()))


def test_serpapi_refuses_to_start_without_a_key() -> None:
    """At construction, not at first use.

    A provider that raised only when the agent finally routed to the web would fail
    mid-demo, on the one query chosen to show it off.
    """
    with pytest.raises(ConfigurationError):
        SerpApiSearchProvider(api_key=None)


@respx.mock
async def test_serpapi_prefers_the_answer_box_then_organic_results(_traced) -> None:
    """The notebook's order of preference, kept deliberately.

    A student who read `Agentic_RAG_Notebook.ipynb` should recognise what comes back.
    """
    respx.get("https://serpapi.com/search.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "answer_box": {"answer": "42", "title": "Direct", "link": "https://x.test/d"},
                "organic_results": [
                    {"title": "First", "snippet": "one", "link": "https://x.test/1"},
                    # No snippet: nothing to ground an answer in, so it is dropped
                    # rather than passed on as a bare title.
                    {"title": "Second", "link": "https://x.test/2"},
                ],
            },
        )
    )

    result = await SerpApiSearchProvider(api_key="k").search("anything")

    assert [s.snippet for s in result.sources] == ["42", "one"]
    assert result.usage.cost_usd > 0


@respx.mock
async def test_a_serpapi_error_never_echoes_the_request(_traced) -> None:
    """The key travels as a *query parameter*, not a header.

    So the usual "include the body, redaction will catch it" habit is wrong here:
    redaction keys on header-shaped patterns, and SerpApi errors echo the request.
    """
    respx.get("https://serpapi.com/search.json").mock(
        return_value=httpx.Response(400, text="bad request for api_key=super-secret")
    )

    with pytest.raises(ProviderError) as raised:
        await SerpApiSearchProvider(api_key="super-secret").search("anything")

    assert "super-secret" not in str(raised.value.detail or "")
    assert "super-secret" not in raised.value.message

