"""`python -m axis` — the pre-flight checks around uvicorn.

Small surface, but it is the first thing anyone runs and the only code whose
failure a person meets before anything else works. Two of the three bugs it has had
were in the twenty lines before uvicorn starts.
"""

from __future__ import annotations

import socket

import pytest

from axis.__main__ import (
    _who_has_the_port,
    port_conflict_message,
    port_in_use,
    stub_provider_message,
)


def test_a_free_port_is_reported_free() -> None:
    # Port 0 asks the OS for any free port, which is then closed — so this is a
    # port that was definitely bindable a moment ago.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    assert port_in_use("127.0.0.1", port) is False


def test_an_occupied_port_is_detected() -> None:
    """The check that turns a misleading crash into an instruction.

    Without it, uvicorn prints "Application startup complete" and *then* the bind
    error, so the console reads as a successful start followed by an unexplained
    `[Errno 10048]` — after the banner has already printed three URLs that will
    never answer. That is how a stale server from ten minutes ago costs someone
    twenty minutes.
    """
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]

        assert port_in_use("127.0.0.1", port) is True


def test_the_probe_does_not_set_reuseaddr() -> None:
    """`SO_REUSEADDR` would make the check quietly useless.

    With it set, the probe bind can succeed alongside a live listener on some
    platforms — reporting a busy port as free, which is worse than not checking at
    all: the caller would go on to hit the raw uvicorn error having been told
    everything was fine.

    Asserted behaviourally rather than by reading the source: a port under an active
    listener must come back busy, twice in a row, with no state carried between.
    """
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]

        assert port_in_use("127.0.0.1", port) is True
        assert port_in_use("127.0.0.1", port) is True


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_the_remedy_names_a_command_for_this_platform(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    """The message has to be usable, not merely correct.

    "Port 8000 is in use" leaves the reader to work out how to find the process,
    and the commands differ per platform in ways nobody remembers under time
    pressure. The port number must appear, or the suggestion cannot be pasted.
    """
    monkeypatch.setattr("axis.__main__.sys.platform", platform)

    remedy = _who_has_the_port(8000)

    assert "8000" in remedy
    if platform == "win32":
        assert "netstat" in remedy and "taskkill" in remedy
    else:
        assert "lsof" in remedy


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_the_whole_conflict_message_is_ascii(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    """A Windows console defaults to cp1252.

    Four separate times now, a non-ASCII character in a startup path has broken
    something in this project: an arrow in the banner, an arrow in the access log,
    box-drawing in the evaluation CLI, and an em-dash in this very message — which
    printed as a replacement character the first time it ran. This message prints on
    the way to exiting, so an encoding error here replaces a helpful message with a
    traceback about the helpful message.

    Asserted on the whole string rather than the command hint alone, because it was
    the surrounding prose that broke, not the part that was already covered.
    """
    monkeypatch.setattr("axis.__main__.sys.platform", platform)

    port_conflict_message("127.0.0.1", 8000).encode("ascii")


def test_the_conflict_message_offers_a_concrete_alternative() -> None:
    """It must be actionable without further thought.

    The reader is usually mid-demo. "Port in use" is a diagnosis; a port number
    they can paste is a fix.
    """
    message = port_conflict_message("127.0.0.1", 8000)

    assert "8000" in message
    assert "--port 8001" in message, "no runnable alternative offered"
    assert "Ctrl+C" in message, (
        "the usual cause is a server whose terminal was closed rather than "
        "interrupted, and the message should say so"
    )


def test_the_test_double_cannot_be_the_demo_provider() -> None:
    """`AXIS_SEARCH__PROVIDER=fake` must stop the demo before it starts.

    It was set in a working `.env`, and the result was a web route that could be
    reached and could never answer: the router classified at 0.9 confidence, the agent
    wrote its own search query, the search ran, and every answer said nothing relevant
    was found. Nothing on screen distinguished that from a broken router.

    `SerpApiSearchProvider` already refuses without a key and `CachedSearchProvider`
    refuses with no recordings, both because a provider that looks configured and
    fails silently in the room must not be reachable by misconfiguration. This is that
    same rule applied to the one provider that had no guard — and it lives at the
    entry point rather than in `build_search_provider` because the suite runs on
    `fake` deliberately.
    """
    message = stub_provider_message("fake")

    assert "fake" in message
    # Every real alternative, named. A refusal that stops the demo without saying what
    # to set instead just moves the confusion an hour earlier.
    assert "serpapi" in message
    assert "cached" in message
    assert "none" in message
    assert "AXIS_SEARCH__API_KEY" in message, (
        "serpapi is the recommended option and it needs a key; a message that omits "
        "that sends the reader straight into the next refusal"
    )


def test_the_test_double_message_is_ascii() -> None:
    """The fifth time would be this one.

    Same reason as the conflict message above: this prints on the way to exiting, so
    a cp1252 encoding error would replace the explanation with a traceback about the
    explanation.
    """
    stub_provider_message("fake").encode("ascii")
