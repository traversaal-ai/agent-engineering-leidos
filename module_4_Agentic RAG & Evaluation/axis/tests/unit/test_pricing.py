"""Cost computation.

The most consequential test here is `test_an_unknown_model_raises`. Returning
zero for an unpriced model would be the convenient implementation and is the bug
worth designing out: an unpriced model costs nothing on paper, so the per-session
cap silently becomes unlimited and the class's budget drains while every check
passes. Failing loudly is the only safe behaviour.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from ai_backend.errors import UnknownModelError
from ai_backend.providers import pricing


def test_an_unknown_model_raises_rather_than_costing_nothing() -> None:
    with pytest.raises(UnknownModelError) as excinfo:
        pricing.cost_of(model="some-model-nobody-priced", prompt_tokens=1_000_000)

    # The message has to say what to do about it.
    assert "pricing.py" in (excinfo.value.detail or "")


def test_cost_is_computed_per_million_tokens() -> None:
    # gpt-4o-mini: $0.15 in / $0.60 out per 1M tokens.
    cost = pricing.cost_of(
        model="gpt-4o-mini", prompt_tokens=1_000_000, completion_tokens=1_000_000
    )

    assert cost == Decimal("0.75")


def test_cost_stays_exact_across_many_small_calls() -> None:
    """Decimal end to end, and this is why.

    A per-session cap is compared against a sum of hundreds of tiny costs. In
    floating point that sum drifts, so a $2.00 cap quietly becomes something
    else. Here 1000 identical calls must total exactly 1000× one call.
    """
    single = pricing.cost_of(
        model="gpt-4o-mini", prompt_tokens=1_000, completion_tokens=500
    )

    total = sum((single for _ in range(1000)), Decimal("0"))

    assert total == single * 1000
    assert isinstance(total, Decimal)


def test_embedding_models_have_no_output_price() -> None:
    cost = pricing.cost_of(model="text-embedding-3-small", prompt_tokens=1_000_000)

    assert cost == Decimal("0.02")


def test_local_models_are_free_at_the_api_boundary() -> None:
    """Honest, and worth saying out loud in class.

    Ollama costs nothing to call, which makes the cost column of a Compare run
    meaningless when a local model is involved — the compute is real, it is just
    being paid for in laptop fan noise. This is the one comparison Axis cannot
    make, and a $0.00 that looks like a win is how a student would misread it.
    """
    assert pricing.cost_of(model="llama3.1", prompt_tokens=1_000_000) == Decimal("0")


def test_the_fake_model_is_not_free() -> None:
    """Otherwise the cost cap would be untestable.

    A fake priced at zero could never push a session over its budget, so the
    cap's own acceptance criterion would have no way to be exercised.
    """
    cost = pricing.cost_of(
        model="fake-model", prompt_tokens=1_000, completion_tokens=500
    )

    assert cost > 0


def test_token_estimation_errs_high() -> None:
    """The estimate feeds a pre-call cap check, so it must not under-count.

    Roughly 3.5 characters per token against a real-world average nearer 4, which
    makes the cap trip slightly early. For a shared classroom budget that is the
    correct direction: an over-cautious refusal is recoverable, an overspend is
    not.
    """
    text = "a" * 400

    estimate = pricing.estimate_tokens(text)

    assert estimate >= len(text) / 4, "the estimate must not under-count"
    assert estimate <= len(text) / 2, "but it should not be wildly pessimistic either"


def test_estimating_an_empty_string_is_zero() -> None:
    assert pricing.estimate_tokens("") == 0


def test_every_priced_model_declares_both_directions() -> None:
    """Guards the table's own shape.

    A missing output price would read as zero and under-charge every completion
    on that model.
    """
    for name, price in pricing.PRICES.items():
        assert price.input >= 0, name
        assert price.output >= 0, name


def test_default_configured_models_are_priced() -> None:
    """The out-of-the-box configuration must not hit `UnknownModelError`.

    A first run that boots and then refuses the first question would be a poor
    introduction, and this is the cheapest possible guard against it.
    """
    from ai_backend.config.settings import EmbeddingSettings, LLMSettings

    for model in (LLMSettings().model, EmbeddingSettings().model):
        pricing.price_for(model)  # must not raise
