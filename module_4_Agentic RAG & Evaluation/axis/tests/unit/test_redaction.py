"""Secret scrubbing on the way into the step store.

System Design Section 6.5 ranks secrets isolation first: an API key must never be
"written into an `AgentStep` shown to students". The trace is the one artefact in
Axis explicitly designed to be projected on a wall and exported into reports, so
this is the highest-consequence leak path in the system.

Two passes are tested separately because they cover different threats. The
exact-value pass catches *our* configured keys and cannot be fooled by an unusual
format. The pattern pass catches keys that are not ours — one pasted into an
uploaded document, or one echoed back inside a provider's error message.
"""

from __future__ import annotations

from ai_backend.contracts.models import AgentStep, StepType
from ai_backend.observability.redact import PLACEHOLDER, redact_step, redact_text


def _step(**kwargs) -> AgentStep:
    return AgentStep(
        session_id="s1", trace_id="t1", step_type=StepType.GENERATE, **kwargs
    )


def test_every_configured_secret_is_redactable() -> None:
    """**`secret_values()` is a hand-written list, so it is checked against the model.**

    It names four `api_key` fields explicitly, and the redactor can only scrub what that
    tuple returns. Add a provider block to `Settings` and forget the one line here, and
    its key survives into a persisted `AgentStep`: the
    exact leak System Design §6.5 ranks first, arriving by omission rather than by any
    visible mistake. Nothing else in the suite would notice, because every other test
    sets the secrets it asserts about.

    So this walks the settings model instead of trusting the list: every nested block
    with an `api_key` field gets a distinct value, and every one of them must come back.
    """
    from pydantic import SecretStr

    from ai_backend.config.settings import Settings

    blocks = [
        name
        for name, field in Settings.model_fields.items()
        if isinstance(field.annotation, type)
        and issubclass(field.annotation, __import__("pydantic").BaseModel)
        and "api_key" in field.annotation.model_fields
    ]
    assert blocks, "no settings block declares an api_key — has the shape changed?"

    planted = {name: f"sk-test-{name}-0123456789abcdef" for name in blocks}
    settings = Settings(**{n: {"api_key": SecretStr(v)} for n, v in planted.items()})

    exposed = settings.secret_values()
    for name, value in planted.items():
        assert value in exposed, (
            f"`{name}.api_key` is configured but absent from `secret_values()`, so the "
            f"redactor cannot scrub it and it can survive into a persisted AgentStep. "
            f"Add `self.{name}.api_key` to the tuple in Settings.secret_values()."
        )

    # And the scrubbing actually happens, so this is not a test of a list alone.
    step = redact_step(
        _step(raw_output=" ".join(planted.values())), secrets=exposed
    )
    for value in planted.values():
        assert value not in (step.raw_output or "")


def test_a_configured_secret_is_removed_from_every_text_field() -> None:
    secret = "sk-proj-averyrealisticlookingkey1234567890"
    step = _step(
        raw_input=f"Authorization: Bearer {secret}",
        raw_output=f"the key {secret} was rejected",
        error=f"401 for {secret}",
        label=f"call with {secret}",
    )

    safe = redact_step(step, (secret,))

    for field in (safe.raw_input, safe.raw_output, safe.error, safe.label):
        assert secret not in (field or ""), field


def test_secrets_are_removed_from_nested_attributes() -> None:
    """`attributes` is free-form, so redaction has to recurse.

    Keys as well as values: a dict can leak through `{"sk-...": 1}`.
    """
    secret = "sk-ant-anotherrealisticlookingkey12345"
    step = _step(
        attributes={
            "headers": {"x-api-key": secret},
            "attempts": [f"tried {secret}", "retried"],
            secret: "used as a key",
        }
    )

    safe = redact_step(step, (secret,))

    assert secret not in str(safe.attributes)


def test_an_unknown_key_shaped_string_is_caught_by_pattern() -> None:
    """A key that is not ours still must not reach a student.

    Adversarial or careless document content is the realistic source here — a
    student uploads a config file, and its contents flow through retrieval into a
    trace step.
    """
    leaked = "sk-proj-notourkeybutstillakey0987654321"

    safe = redact_text(f"the document contained {leaked}", ())

    assert leaked not in (safe or "")
    assert PLACEHOLDER in (safe or "")


def test_common_credential_shapes_are_recognised() -> None:
    for candidate in (
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz012345",
        "AIzaSyAbCdEfGhIjKlMnOpQrStUvWxYz0123456",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig",
        "x-api-key: abcdef1234567890abcdef",
        'api_key="hunter2hunter2hunter2"',
        "password: correcthorsebatterystaple",
    ):
        safe = redact_text(candidate, ()) or ""
        assert PLACEHOLDER in safe, f"not redacted: {candidate}"


def test_an_underscore_prefixed_key_is_recognised_even_when_it_is_not_ours() -> None:
    """`sk_` with an underscore, which the pattern missed until it was widened.

    **The empty tuple is the whole point of this test.** With no configured secrets the
    exact-value pass has nothing to match, so only the pattern pass can catch this — and
    that is the case it exists for: a key that is *not* ours, pasted into an uploaded
    document or echoed back inside a provider's error message. A key Axis is configured
    with is always safe, scrubbed by exact value whatever its shape — which is exactly
    why a gap in the *pattern* stays invisible until a document contains one.
    """
    foreign = "sk_9f2c41ab7de84c05be1730d6a4f8c92e15b0da77"

    for candidate in (
        foreign,
        f"the provider rejected {foreign} as invalid",
        f'{{"x-api-key": "{foreign}"}}',
    ):
        safe = redact_text(candidate, ()) or ""
        assert PLACEHOLDER in safe, f"not redacted: {candidate}"
        assert foreign not in safe, safe


def test_a_short_secret_does_not_destroy_the_whole_string() -> None:
    """Guards against an over-eager replacement.

    A misconfigured or placeholder secret of two characters would otherwise
    replace every occurrence of those characters throughout the trace, shredding
    it. The exact-value pass therefore ignores anything under 8 characters, and
    such a value would not be a working key anyway.
    """
    safe = redact_text("the retrieval returned 3 chunks", ("ab",))

    assert safe == "the retrieval returned 3 chunks"


def test_ordinary_trace_content_is_left_alone() -> None:
    """Redaction must not corrupt the trace it protects.

    Over-redaction is a real failure too: a trace full of `[redacted]` teaches
    nothing, and a student would reasonably conclude the tool is broken.
    """
    original = (
        "VectorRetriever.retrieve('parental leave', top_k=5) → 3 chunks "
        "(scores 0.81, 0.77, 0.71) from policy.pdf p.4"
    )

    assert redact_text(original, ()) == original


def test_redaction_returns_a_copy() -> None:
    """The caller's own object is untouched, so redaction is safe to apply twice."""
    secret = "sk-proj-averyrealisticlookingkey1234567890"
    step = _step(raw_output=f"leaked {secret}")

    safe = redact_step(step, (secret,))

    assert secret in (step.raw_output or ""), "the original should be unmodified"
    assert secret not in (safe.raw_output or "")
    assert redact_step(safe, (secret,)).raw_output == safe.raw_output


def test_none_fields_survive_redaction() -> None:
    step = _step()

    safe = redact_step(step, ("sk-proj-something0123456789",))

    assert safe.raw_input is None
    assert safe.raw_output is None
    assert safe.error is None
