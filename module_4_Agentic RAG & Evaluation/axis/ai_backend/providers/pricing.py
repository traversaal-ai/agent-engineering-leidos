"""Token-to-dollar conversion.

Axis prices its own calls rather than trusting a vendor response, because vendors
report token *usage*, not cost, and the per-session cap is only as trustworthy as
this table.

⚠️ VERIFY BEFORE EACH WORKSHOP. Provider pricing changes without notice, and a
stale figure here produces a cap that is wrong in whichever direction is least
convenient. Check the current rate cards and update `PRICES` as part of workshop
prep — the `test_pricing_table_is_complete` test will tell you if a configured
model is missing, but nothing can tell you a price is out of date except looking.

The most important behaviour in this module is what happens for a model that is
*not* listed: `UnknownModelError`. It would be far easier to return zero, and
that is precisely the bug worth designing out — an unpriced model would cost
nothing on paper, so the cost cap would silently become unlimited and the class's
budget would drain with every check passing.
"""

from __future__ import annotations

from decimal import Decimal

from ai_backend.errors import UnknownModelError

_MILLION = Decimal("1000000")


class ModelPrice:
    """USD per million tokens.

    Embedding models have no output price; `output` is zero for them rather than
    absent, so callers need no special case.
    """

    __slots__ = ("input", "output")

    def __init__(self, input_per_mtok: str, output_per_mtok: str = "0") -> None:
        self.input = Decimal(input_per_mtok)
        self.output = Decimal(output_per_mtok)


# Prices in USD per 1M tokens. Last reviewed: see the warning above — treat any
# figure here as needing confirmation before you rely on it for a budget.
PRICES: dict[str, ModelPrice] = {
    # ---- OpenAI, chat -----------------------------------------------------
    "gpt-4o": ModelPrice("2.50", "10.00"),
    "gpt-4o-mini": ModelPrice("0.15", "0.60"),
    # ---- OpenAI, embeddings ----------------------------------------------
    "text-embedding-3-small": ModelPrice("0.02"),
    "text-embedding-3-large": ModelPrice("0.13"),
    # ---- Anthropic, chat -------------------------------------------------
    "claude-opus-5": ModelPrice("15.00", "75.00"),
    "claude-sonnet-5": ModelPrice("3.00", "15.00"),
    "claude-haiku-4-5-20251001": ModelPrice("1.00", "5.00"),
    # ---- Local models ----------------------------------------------------
    # Genuinely free at the API boundary, which is the whole appeal of the
    # keyless path: a student can explore without spending anything. Note this
    # makes cost comparisons against cloud providers meaningless, which is worth
    # saying out loud in class rather than letting a $0.00 column mislead.
    "llama3.1": ModelPrice("0"),
    "llama3.2": ModelPrice("0"),
    "mistral": ModelPrice("0"),
    "nomic-embed-text": ModelPrice("0"),
    "mxbai-embed-large": ModelPrice("0"),
    # ---- Test double -----------------------------------------------------
    # Non-zero on purpose. A fake priced at zero could never exercise the cost
    # cap, so the cap's own acceptance test would be untestable.
    "fake-model": ModelPrice("1.00", "3.00"),
    "fake-embedding": ModelPrice("0.10"),
}


# Search is billed per *request*, not per token — a search API charges the same for
# a three-word query as a thirty-word one. `PRICES` cannot express that: a per-MTok
# figure applied to a query of a few tokens rounds to approximately nothing, so a
# search call would have read as $0.00 in the Compare table and the web route would
# have looked free. Which is the same class of bug as an unpriced model, and worth
# the separate table rather than a fudged token rate.
#
# ⚠️ Same warning as above: verify before each workshop.
SEARCH_PRICES: dict[str, Decimal] = {
    # SerpApi's plans are sold as monthly search allowances rather than per-call, so
    # this is a plan's price divided by its included searches — the marginal cost of
    # one search on a small plan, which is the honest figure for a classroom.
    "serpapi": Decimal("0.015"),
    # Replays recorded results. No request leaves the machine, so there is nothing
    # to charge — and unlike the local LLMs above, this genuinely does not distort a
    # comparison: `cached` exists to make a *demo* reproducible, not to measure cost.
    "cached": Decimal("0"),
    # Non-zero for the same reason `fake-model` is: a search cap whose calls cost
    # nothing could not be shown to bound anything.
    "fake": Decimal("0.005"),
}


def search_cost_of(provider: str) -> Decimal:
    """Cost of one search call, in USD.

    Raises for an unlisted provider rather than returning zero, exactly as
    `price_for` does. An unpriced search provider would make the per-session cap
    unlimited along the one dimension it does not otherwise track.
    """
    try:
        return SEARCH_PRICES[provider]
    except KeyError:
        raise UnknownModelError(
            f"No price is recorded for search provider {provider!r}, so its cost "
            f"cannot be computed and the per-session cost cap cannot be enforced.",
            detail=(
                "Add an entry to SEARCH_PRICES in ai_backend/providers/pricing.py, "
                f"or configure one that is listed: {', '.join(sorted(SEARCH_PRICES))}."
            ),
        ) from None


def price_for(model: str) -> ModelPrice:
    try:
        return PRICES[model]
    except KeyError:
        raise UnknownModelError(
            f"No price is recorded for model {model!r}, so its cost cannot be "
            f"computed and the per-session cost cap cannot be enforced.",
            detail=(
                "Add an entry to PRICES in ai_backend/providers/pricing.py, or "
                "configure a model that is already listed: "
                f"{', '.join(sorted(PRICES))}."
            ),
        ) from None


def cost_of(*, model: str, prompt_tokens: int, completion_tokens: int = 0) -> Decimal:
    """Exact cost of a call, in USD.

    Kept in `Decimal` end to end. Costs are summed hundreds of times across a
    session and then compared against a cap; accumulating float error into that
    comparison is how a $2.00 cap turns into a $2.04 cap.
    """
    price = price_for(model)
    return (
        price.input * Decimal(prompt_tokens) + price.output * Decimal(completion_tokens)
    ) / _MILLION


def estimate_tokens(text: str) -> int:
    """Rough token count from character length.

    Deliberately approximate and deliberately biased high (~3.5 chars per token
    against a real-world average nearer 4). A real tokenizer would mean a
    `tiktoken` dependency per vendor, and this number's only job is to feed a
    pre-call cost estimate. Erring high makes the cap trip slightly early, which
    is the correct direction for a shared classroom budget: an over-cautious
    refusal is recoverable, an overspend is not.
    """
    if not text:
        return 0
    # len / 3.5, in integer arithmetic, rounded up.
    return max(1, (len(text) * 2 + 6) // 7)
