"""`python -m axis` — start all three layers in one process.

The entry point PRD Section 6's single-machine criterion is written against:
"when Axis is started, then all three layers come up and pass the
/api/v1/health check". One command, one process, one thing to keep alive.
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys

import uvicorn

from ai_backend.config.settings import get_settings


def port_in_use(host: str, port: int) -> bool:
    """Whether something already holds this address.

    A pre-flight check, because uvicorn's own failure is actively misleading. It
    prints "Application startup complete" and *then* the bind error, so the console
    reads as a successful start followed by an unexplained `[Errno 10048]` — and by
    then the banner has already printed three URLs that will not answer.

    No `SO_REUSEADDR`. Setting it would let this bind succeed alongside an existing
    listener on some platforms, which is precisely the false negative that would
    make the check worse than useless.

    There is a race here — the port could be taken between this check and uvicorn's
    bind — and that is fine. This exists to give a good message in the common case;
    uvicorn's error remains the backstop for the rare one.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return True
    return False


def _who_has_the_port(port: int) -> str:
    """The platform's command for finding the offending process.

    Worth printing rather than leaving to the reader: the answer is almost always a
    previous Axis that was closed by shutting its terminal rather than Ctrl+C, and
    the commands to find it differ per platform in ways nobody remembers.
    """
    if sys.platform == "win32":
        return (
            f"  netstat -ano | findstr :{port}       (last column is the PID)\n"
            f"  taskkill /PID <pid> /F"
        )
    return f"  lsof -i :{port}\n  kill <pid>"


def port_conflict_message(host: str, port: int) -> str:
    """What the operator reads when the port is taken.

    A function rather than an inline string so the whole message is testable —
    including that it is ASCII. The first draft of this very message contained an
    em-dash and printed a replacement character on the Windows console, which is
    the fourth time that has happened in this project.
    """
    return (
        f"Port {port} on {host} is already in use, so Axis did not start.\n\n"
        f"Usually this is an earlier Axis still running. Closing its terminal "
        f"window does not\nstop it; Ctrl+C does. Either stop it:\n\n"
        f"{_who_has_the_port(port)}\n\n"
        f"or run on a different port:\n\n"
        f"  python -m axis --port {port + 1}\n"
    )


def stub_provider_message(provider: str) -> str:
    """What the operator reads when the demo is configured with a test double.

    ASCII only and a function, for the reasons `port_conflict_message` records above.
    """
    return (
        f"AXIS_SEARCH__PROVIDER={provider} is the test double, so Axis did not "
        f"start.\n\n"
        f"It returns one canned placeholder for every query and charges $0.005 a "
        f"call. The\nweb route can be reached and can never answer: the router "
        f"classifies correctly, the\nagent writes a search query, the search runs, "
        f"and the answer is always that nothing\nrelevant was found.\n\n"
        f"Set one that can answer:\n\n"
        f"  AXIS_SEARCH__PROVIDER=serpapi   live search, needs AXIS_SEARCH__API_KEY\n"
        f"  AXIS_SEARCH__PROVIDER=cached    replays recordings, offline and "
        f"rehearsable\n"
        f"  AXIS_SEARCH__PROVIDER=none      no web route at all\n"
    )


def main() -> None:
    settings = get_settings()

    parser = argparse.ArgumentParser(
        prog="axis", description="Start the Axis teaching platform."
    )
    parser.add_argument("--host", default=settings.server.host)
    parser.add_argument("--port", type=int, default=settings.server.port)
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Reload on code changes. Development only — never during a live demo.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    # Checked before the banner, so the URLs are never printed for a server that
    # is not going to come up.
    if port_in_use(args.host, args.port):
        print(port_conflict_message(args.host, args.port), file=sys.stderr)
        raise SystemExit(1)

    # **The test double is refused here rather than in `build_search_provider`,
    # and the placement is the whole point.** `SerpApiSearchProvider` refuses
    # without a key and `CachedSearchProvider` refuses with no recordings, both for
    # the same stated reason: a search provider that looks configured, gets routed
    # to, and fails silently in the room must not be reachable by misconfiguration.
    # `fake` was the one that had no such guard, and it produced exactly that
    # failure — a correct routing decision, a real search call, and an answer saying
    # nothing was found, three times in a row.
    #
    # It cannot go in `build_search_provider` because the suite legitimately runs on
    # `fake`: `tests/conftest.py` configures it so the toggle has a capability to
    # report, and `test_the_control_is_absent_when_no_provider_is_configured` asserts
    # that. This entry point is where "a person is starting the demo" is known, and
    # tests never come through it.
    if settings.search.provider == "fake":
        print(stub_provider_message(settings.search.provider), file=sys.stderr)
        raise SystemExit(1)

    # ASCII only. A Windows console defaults to cp1252, which cannot encode "→"
    # — and `print` raising in the banner takes the whole process down before
    # uvicorn is even reached. A decorative character is not worth making the
    # documented start command fail on one of the three platforms an instructor
    # might teach from.
    base = f"http://{args.host}:{args.port}"
    print(f"  Axis   -> {base}")
    print(f"  API    -> {base}/api/v1/docs")
    print(f"  Health -> {base}/api/v1/health")

    # Passed as an import string rather than an app object so --reload works;
    # uvicorn's reloader needs to be able to re-import the module.
    uvicorn.run(
        "axis.asgi:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
