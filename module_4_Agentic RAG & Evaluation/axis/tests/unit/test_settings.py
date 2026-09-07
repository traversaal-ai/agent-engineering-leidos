"""Configuration, secrets handling, and fail-fast validation.

Two threads run through these tests. The first is that a secret should be hard to
leak by accident — hence `SecretStr`, and hence the assertion that a `repr()`
shows a mask. The second is that a bad configuration should produce a message an
instructor can act on twenty minutes before a class, naming the exact environment
variable at fault.
"""

from __future__ import annotations

import os

import pytest
from pydantic import SecretStr

from ai_backend.config.settings import (
    TOOL_CAPABLE_PROVIDERS,
    Settings,
    for_frontend,
    get_settings,
)
from ai_backend.errors import ConfigurationError


def _settings(**overrides) -> Settings:
    base = {
        "llm": {"provider": "fake", "model": "fake-model"},
        "embedding": {"provider": "fake", "model": "fake-embedding"},
        "storage": {"db_path": ":memory:"},
    }
    base.update(overrides)
    return Settings(**base)


# ---------------------------------------------------------------------------
# Secret handling
# ---------------------------------------------------------------------------


def test_a_secret_does_not_appear_in_a_repr() -> None:
    """`SecretStr` makes leaking require an explicit, greppable call.

    The realistic accident is not `print(api_key)` — it is a settings object
    landing in a log line or a traceback frame.
    """
    settings = _settings(
        llm={"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-realkey123456789"}
    )

    rendered = repr(settings) + str(settings)

    assert "sk-realkey123456789" not in rendered
    assert "**********" in rendered


def test_secret_values_exposes_only_configured_secrets() -> None:
    """The redactor's input. Deliberately the one place that unwraps secrets."""
    settings = _settings(
        llm={"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-llmkey123456789"},
        embedding={
            "provider": "openai",
            "model": "text-embedding-3-small",
            "api_key": "sk-embedkey123456789",
        },
    )

    values = settings.secret_values()

    assert set(values) == {"sk-llmkey123456789", "sk-embedkey123456789"}


def test_secret_values_skips_unset_and_empty_keys() -> None:
    settings = _settings(llm={"provider": "ollama", "model": "llama3.1", "api_key": None})

    assert settings.secret_values() == ()


def test_no_test_can_read_a_developers_own_env_file() -> None:
    """Guards the isolation that keeps a real key out of a pytest diff.

    The test above is the one that leaked: it overrode `llm` but not `embedding`,
    so a real `AXIS_EMBEDDING__API_KEY` in `.env` fell through and pytest printed
    it in full. `secret_values()` returns unmasked strings by design, so `SecretStr`
    offers no protection at that point — the only defence is that the value was
    never loaded.

    Asserted here rather than trusted to the fixture, because the failure mode is
    silent: without this, someone removing `_no_ambient_config` sees a green suite
    on a machine with no `.env` and finds out on a machine that has one.
    """
    assert Settings.model_config["env_file"] is None, (
        "tests are reading a .env file — a developer's real API key can reach an "
        "assertion diff. See _no_ambient_config in tests/conftest.py."
    )
    assert not [k for k in os.environ if k.startswith("AXIS_")]
    # The end-to-end property: a field nothing overrode stays unset.
    assert Settings().embedding.api_key is None


def test_the_frontend_view_cannot_carry_a_secret() -> None:
    """Structural, not disciplined.

    `FrontendSettings` has no secret field, so no amount of later carelessness in
    a template or a view can put a key in front of a browser.
    """
    settings = _settings(
        llm={"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-realkey123456789"}
    )

    view = for_frontend(settings)

    assert "sk-realkey123456789" not in repr(view)
    assert not any(
        isinstance(value, SecretStr) for value in view.model_dump().values()
    )
    assert "api_key" not in view.model_dump()


# ---------------------------------------------------------------------------
# Fail-fast validation
# ---------------------------------------------------------------------------


def test_a_valid_configuration_passes() -> None:
    _settings().validate_runtime()  # must not raise


def test_a_cloud_provider_without_a_key_is_refused() -> None:
    settings = _settings(llm={"provider": "openai", "model": "gpt-4o-mini", "api_key": None})

    with pytest.raises(ConfigurationError) as excinfo:
        settings.validate_runtime()

    # The message must name the variable to set — the reader is usually configuring
    # Axis, not reading its source.
    assert "AXIS_LLM__API_KEY" in (excinfo.value.detail or "")


def test_ollama_needs_no_key() -> None:
    """The zero-key path has to actually work with zero keys.

    This is what makes PRD Section 6's "fresh machine with only API keys
    configured" honestly satisfiable on a laptop with no budget approved.
    """
    settings = _settings(
        llm={"provider": "ollama", "model": "llama3.1"},
        embedding={"provider": "ollama", "model": "nomic-embed-text"},
    )

    settings.validate_runtime()  # must not raise


def test_ollama_still_boots_despite_not_supporting_tools() -> None:
    """The agentic strategies need tool calling; the single-shot ones do not.

    Refusing to start would take Naive RAG away from anyone running keyless, which
    is worse than the problem. The scoped consequence — the agentic strategy being
    marked unavailable with a reason — is enforced in `runtime.py` and covered by
    `test_agentic_strategies_are_unavailable_without_tool_calling`.
    """
    settings = _settings(
        llm={"provider": "ollama", "model": "llama3.1"},
        embedding={"provider": "ollama", "model": "nomic-embed-text"},
    )

    settings.validate_runtime()
    assert settings.llm.provider not in TOOL_CAPABLE_PROVIDERS


def test_an_agent_bound_of_zero_is_refused() -> None:
    """Unvalidated until Milestone 1, when the bounds acquired a consumer.

    Zero is the dangerous value precisely because it looks configured: the agentic
    strategies would still be listed as available, the trace would still show route
    and decompose, and the escalation loop would simply never run — so a class would
    be shown an agent that cannot act, with nothing saying why.
    """
    for field, variable in (
        ("max_agent_iterations", "AXIS_CAPS__MAX_AGENT_ITERATIONS"),
        ("max_tool_calls_per_query", "AXIS_CAPS__MAX_TOOL_CALLS_PER_QUERY"),
    ):
        settings = _settings(caps={field: 0})

        with pytest.raises(ConfigurationError) as excinfo:
            settings.validate_runtime()

        assert variable in (excinfo.value.detail or ""), field


def test_too_few_llm_calls_for_an_agentic_query_is_refused() -> None:
    """Route, decompose, synthesize. Below three, an agentic query cannot finish."""
    settings = _settings(caps={"max_llm_calls_per_query": 2})

    with pytest.raises(ConfigurationError) as excinfo:
        settings.validate_runtime()

    assert "AXIS_CAPS__MAX_LLM_CALLS_PER_QUERY" in (excinfo.value.detail or "")


def test_anthropic_embeddings_are_refused_with_an_explanation() -> None:
    """Anthropic publishes no embeddings API.

    Caught at startup with the reason, rather than as a puzzling failure at the
    first query. The message also has to point at the workable configuration,
    since "anthropic for chat, openai for embeddings" is a perfectly sensible
    thing to want.
    """
    settings = _settings(
        embedding={"provider": "anthropic", "model": "irrelevant", "api_key": "sk-x"}
    )

    with pytest.raises(ConfigurationError) as excinfo:
        settings.validate_runtime()

    detail = excinfo.value.detail or ""
    assert "embeddings" in detail.lower() or "embeddings" in excinfo.value.message.lower()
    assert "openai" in detail.lower()


def test_an_unknown_provider_is_refused_and_lists_the_options() -> None:
    settings = _settings(llm={"provider": "gpt5-turbo-max", "model": "x"})

    with pytest.raises(ConfigurationError) as excinfo:
        settings.validate_runtime()

    detail = excinfo.value.detail or ""
    for supported in ("openai", "anthropic", "ollama"):
        assert supported in detail


def test_a_zero_cost_cap_is_refused() -> None:
    """A cap of zero would reject every query.

    Almost certainly a typo or an unset variable rather than an intention, and
    silently accepting it would present as Axis being completely broken.
    """
    settings = _settings(caps={"max_cost_usd_per_session": 0})

    with pytest.raises(ConfigurationError) as excinfo:
        settings.validate_runtime()

    assert "MAX_COST_USD_PER_SESSION" in (excinfo.value.detail or "")


def test_all_configuration_problems_are_reported_at_once() -> None:
    """One boot, one complete list.

    Fixing configuration one error per restart is a miserable way to spend the
    minutes before a class.
    """
    settings = _settings(
        llm={"provider": "openai", "model": "gpt-4o-mini", "api_key": None},
        embedding={"provider": "anthropic", "model": "x"},
        caps={"max_cost_usd_per_session": 0},
    )

    with pytest.raises(ConfigurationError) as excinfo:
        settings.validate_runtime()

    detail = excinfo.value.detail or ""
    assert detail.count("- ") >= 3, detail


# ---------------------------------------------------------------------------
# Environment binding
# ---------------------------------------------------------------------------


def test_nested_settings_bind_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`AXIS_LLM__PROVIDER` → `settings.llm.provider`, via the `__` delimiter."""
    monkeypatch.setenv("AXIS_LLM__PROVIDER", "ollama")
    monkeypatch.setenv("AXIS_LLM__MODEL", "llama3.2")
    monkeypatch.setenv("AXIS_CAPS__MAX_REQUESTS_PER_SESSION", "7")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.llm.provider == "ollama"
    assert settings.llm.model == "llama3.2"
    assert settings.caps.max_requests_per_session == 7

    get_settings.cache_clear()


def test_settings_are_cached_per_process() -> None:
    """One settings object, so every layer sees the same configuration."""
    get_settings.cache_clear()

    assert get_settings() is get_settings()

    get_settings.cache_clear()


def test_upload_limit_matches_the_prd() -> None:
    """PRD Section 5 says five documents. The default should not need explaining."""
    assert _settings().upload.max_files_per_session == 5
