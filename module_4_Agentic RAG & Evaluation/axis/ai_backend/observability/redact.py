"""Secret scrubbing, applied to every `AgentStep` before it is persisted.

The trace is the one part of Axis explicitly designed to be shown to students,
projected on a classroom wall, and exported into a report. That makes it the
highest-risk place for a key to surface, so redaction runs at the store boundary
rather than at each call site — a call site can be forgotten; the boundary cannot.

Two complementary passes, because either alone leaves a real gap:

- **Exact-value** replacement of every secret in the current configuration. This
  is the reliable pass: it cannot be fooled by an unusual key format.
- **Pattern** replacement for credential shapes generally. This catches keys that
  are *not* ours — a key pasted into an uploaded document, or one echoed back in
  a provider error message.
"""

from __future__ import annotations

import re
from typing import Any

from ai_backend.contracts.models import AgentStep

PLACEHOLDER = "[redacted]"

# Ordered most-specific first, so a vendor-shaped key is labelled as such rather
# than being swallowed by the generic bearer-token rule.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    # OpenAI-style, including project/service-account variants — and every other vendor
    # that has settled on an `sk` prefix, several of which separate it with an
    # **underscore** rather than a hyphen.
    #
    # `sk[-_]` rather than `sk-`, and the underscore is not hypothetical: keys of that
    # shape are issued today. This is the pass that catches keys which are *not* ours —
    # one pasted into an uploaded document, or echoed back inside a provider's error
    # message — and a configured key is already scrubbed by exact value from
    # `Settings.secret_values()` whatever its shape, which is precisely why a gap here
    # stays invisible until someone's document contains one.
    re.compile(r"sk[-_](?:proj-|svcacct-)?[A-Za-z0-9_\-]{16,}"),
    # Anthropic-style.
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}"),
    # Google / GCP-style.
    re.compile(r"AIza[A-Za-z0-9_\-]{20,}"),
    # HTTP credential headers, however they were spelled.
    re.compile(r"(?i)\b(?:authorization|x-api-key)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
    # A generic `api_key: value` assignment in JSON, a dict repr, or a log line.
    re.compile(r"(?i)\b(?:api[-_]?key|secret|password|token)\b[\"']?\s*[:=]\s*[\"']?[^\s\"',}]{8,}"),
)


def _mask_text(text: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        # Guard against a short or empty value blowing away the whole string.
        if len(secret) >= 8:
            text = text.replace(secret, PLACEHOLDER)
    for pattern in _PATTERNS:
        text = pattern.sub(PLACEHOLDER, text)
    return text


def _mask_value(value: Any, secrets: tuple[str, ...]) -> Any:
    """Recurse into whatever shape `attributes` happens to hold.

    Attributes are free-form by design, so this cannot assume a schema. Keys are
    scrubbed as well as values: a dict can leak through `{"sk-abc...": 1}`.
    """
    if isinstance(value, str):
        return _mask_text(value, secrets)
    if isinstance(value, dict):
        return {_mask_value(k, secrets): _mask_value(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_value(v, secrets) for v in value]
    if isinstance(value, tuple):
        return tuple(_mask_value(v, secrets) for v in value)
    return value


def redact_text(text: str | None, secrets: tuple[str, ...] = ()) -> str | None:
    if text is None:
        return None
    return _mask_text(text, secrets)


def redact_step(step: AgentStep, secrets: tuple[str, ...] = ()) -> AgentStep:
    """Return a copy of `step` with every free-text field scrubbed.

    Returns a copy rather than mutating, so a caller holding the original for its
    own purposes is unaffected and the function is safe to apply twice.
    """
    return step.model_copy(
        update={
            "raw_input": redact_text(step.raw_input, secrets),
            "raw_output": redact_text(step.raw_output, secrets),
            "narration": redact_text(step.narration, secrets),
            "error": redact_text(step.error, secrets),
            "label": _mask_text(step.label, secrets),
            "attributes": _mask_value(step.attributes, secrets),
        }
    )
