"""Per-query budget enforcement, with a running total.

Naive RAG's single LLM call hid a defect that the agent loop makes real. The
original check compared each call's estimate against `budget.max_cost_usd` — the
*whole* remaining session allowance — and nothing decremented it. With one call per
query that is correct. With five, each call is checked against the same untouched
balance, so five calls each individually affordable can collectively exceed the cap
and every one of them passes its check.

That is not a rounding error; it is the cap not working. CLAUDE.md requires every
external call to respect the cap "checked *before* the call is made, not after", and
a check against a number that never moves does not do that.

`QuerySpend` is the fix: one object per query, threaded through everything that can
spend. It holds three of the four `QueryBudget` bounds (the fourth,
`max_agent_iterations`, belongs to the loop) and refuses the call that would breach
one, before it is made.

Reserve-then-record, deliberately:

    spend.reserve(prompt_tokens=..., max_completion_tokens=...)   # may raise
    completion = await llm.complete(...)
    spend.record(completion.usage)                                # the real number

`reserve` charges the *estimate*, which is priced at the maximum completion length,
so the ceiling is enforced against the worst case rather than the hoped-for one.
`record` then replaces that reservation with what the call actually cost. Skipping
`record` leaves the pessimistic estimate standing — the loop under-spends rather
than over-spends, which is the right way for this to fail.
"""

from __future__ import annotations

from decimal import Decimal

from ai_backend.contracts.models import Usage
from ai_backend.contracts.pipeline import QueryBudget
from ai_backend.contracts.providers import LLMProvider
from ai_backend.errors import BudgetExceededError


class QuerySpend:
    """The running cost and call count for one query."""

    def __init__(self, budget: QueryBudget, *, llm: LLMProvider) -> None:
        self._budget = budget
        self._llm = llm
        self._limit = Decimal(str(budget.max_cost_usd))
        self._reserved = Decimal("0")
        # Every LLM call this query has made, summed. This is what the `Answer`
        # reports and therefore what the session ledger is charged.
        #
        # Accumulating the full `Usage` rather than just a cost is what makes the
        # figure attributable: an agentic answer costing four times a naive one is a
        # claim, and "34,000 prompt tokens across three calls" is the evidence.
        self.usage = Usage()
        self.llm_calls = 0
        self.tool_calls = 0
        # Counted separately from `tool_calls` even though a search arrives through a
        # tool. The tool budget bounds how much the agent *explores*; this bounds how
        # much it spends at a third party, which is a different concern with a
        # different unit of cost and a different blast radius if it is wrong.
        self.search_calls = 0

    # -- what has been spent -----------------------------------------------

    @property
    def spent(self) -> Decimal:
        """Committed cost plus anything reserved for a call now in flight."""
        return self.usage.cost_usd + self._reserved

    @property
    def remaining(self) -> Decimal:
        return max(Decimal("0"), self._limit - self.spent)

    # -- LLM calls ---------------------------------------------------------

    def reserve(self, *, prompt_tokens: int, max_completion_tokens: int) -> Decimal:
        """Authorise one LLM call, or raise before it happens.

        Both bounds are checked, and the call-count one first: "you have used all
        20 of this query's calls" is a clearer thing for a student to read than a
        cost figure, and it is the bound an agent loop hits first.
        """
        if self.llm_calls >= self._budget.max_llm_calls:
            raise BudgetExceededError(
                f"This query has already made {self.llm_calls} LLM calls, which is "
                f"its limit of {self._budget.max_llm_calls}.",
                detail=(
                    "No further call was made. Raise AXIS_CAPS__MAX_LLM_CALLS_PER_QUERY "
                    "if an agentic run legitimately needs more."
                ),
            )

        estimate = self._llm.estimate_cost(
            prompt_tokens=prompt_tokens, max_completion_tokens=max_completion_tokens
        )
        if self.spent + estimate > self._limit:
            raise BudgetExceededError(
                f"This call is estimated at ${estimate:.4f}, and this query has "
                f"already spent ${self.spent:.4f} of its ${self._limit:.4f} "
                f"allowance.",
                detail="No LLM call was made. Start a new session to continue.",
            )

        self._reserved += estimate
        self.llm_calls += 1
        return estimate

    def record(self, usage: Usage) -> None:
        """Replace the outstanding reservation with what the call really cost.

        Must be called after every completion, and not only for the cap's sake:
        `self.usage` is what the pipeline reports on the `Answer`, so a call that is
        never recorded is a call the session is never charged for and that Compare
        mode never sees. That is how a router's cost silently vanished from an
        agentic run's total until the golden set showed both strategies costing
        exactly the same.
        """
        self.usage = self.usage + usage
        self._reserved = Decimal("0")

    def reserve_for(self, messages: object, *, max_completion_tokens: int) -> Decimal:
        """`reserve`, counting the prompt tokens itself.

        Saves every call site from repeating the same `sum(count_tokens(...))`, and
        more importantly makes it impossible for one of them to count the tokens
        differently from another and get a different answer about affordability.
        """
        prompt_tokens = sum(
            self._llm.count_tokens(m.content) for m in messages  # type: ignore[attr-defined]
        )
        return self.reserve(
            prompt_tokens=prompt_tokens, max_completion_tokens=max_completion_tokens
        )

    # -- search calls ------------------------------------------------------

    def reserve_search(self, *, estimate: Decimal) -> None:
        """Authorise one web search, or raise before the request is made.

        **Its own bound rather than a share of the LLM one.** Search is billed per
        request, so the token estimate that guards `reserve` cannot bound it — a
        three-word query priced per million tokens rounds to nothing, and the cap
        would be unlimited along this axis while every check passed. That is the
        same failure `pricing.price_for` raises to prevent for an unlisted model.

        A raise rather than a predicate, unlike `can_call_tool`: exceeding the
        *search* allowance means a paid third-party request would have been made,
        which is the thing the cap exists to stop. The caller catches it and records
        the stop, exactly as it already does for `reserve`.
        """
        if self.search_calls >= self._budget.max_search_calls:
            raise BudgetExceededError(
                f"This query has already made {self.search_calls} web searches, "
                f"which is its limit of {self._budget.max_search_calls}.",
                detail=(
                    "No search was made. Raise AXIS_CAPS__MAX_SEARCH_CALLS_PER_QUERY "
                    "if a query legitimately needs more."
                ),
            )
        if self.spent + estimate > self._limit:
            raise BudgetExceededError(
                f"This web search costs ${estimate:.4f}, and this query has already "
                f"spent ${self.spent:.4f} of its ${self._limit:.4f} allowance.",
                detail="No search was made. Start a new session to continue.",
            )

        self._reserved += estimate
        self.search_calls += 1

    # -- tool calls --------------------------------------------------------

    def can_call_tool(self) -> bool:
        """Whether the tool budget has room left.

        A predicate rather than a raise: hitting the tool budget is not an error.
        Section 11 wants it rendered as "stopped: budget reached" with a partial
        synthesis, so the loop needs to *ask* and then stop gracefully, which an
        exception would make awkward.
        """
        return self.tool_calls < self._budget.max_tool_calls

    def count_tool_call(self) -> None:
        self.tool_calls += 1
