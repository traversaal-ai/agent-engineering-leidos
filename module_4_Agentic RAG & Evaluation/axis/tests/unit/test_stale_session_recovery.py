"""A cookie naming a session that no longer exists must not be a 500.

Found on the hosted deployment, where the session store is `:memory:` and an
instance can be recycled between two requests from the same browser. The cookie
survives; the session it names does not. The same thing happens locally every time
the process restarts with a tab still open.

`_session` used to return the cookie's values whenever both were present, so the
dead id went straight to the Backend, which answered `401 Unauthorized` — correctly,
it has no such session — and `raise_for_status()` turned that into an Internal
Server Error. The student's way out was to clear cookies, which is not something to
ask of a class mid-demo.
"""

from __future__ import annotations

import httpx

STALE = "3ec43cc1352c40dd8100fed343142deb"


async def test_asking_with_a_dead_session_cookie_recovers(
    client: httpx.AsyncClient,
) -> None:
    """The exact request that produced the 500, and what it should do instead.

    A fresh session, an honest empty board, and the question actually answered
    against it — not a stack trace.
    """
    client.cookies.set("axis_session", STALE)
    client.cookies.set("axis_token", "a-token-for-a-session-that-is-gone")

    response = await client.post(
        "/ask",
        data={"question": "What are the payment terms?", "strategy": "naive_rag"},
    )

    assert response.status_code == 200, response.text[:400]
    # And the browser is moved off the dead id rather than being left to present it
    # again on the next request.
    assert response.cookies.get("axis_session") not in (None, STALE)


async def test_a_page_load_with_a_dead_session_cookie_recovers(
    client: httpx.AsyncClient,
) -> None:
    """Not only the ask path — every route that mints a session goes through it."""
    client.cookies.set("axis_session", STALE)
    client.cookies.set("axis_token", "a-token-for-a-session-that-is-gone")

    for path in ("/", "/compare", "/summarize", "/why-agentic"):
        response = await client.get(path)
        assert response.status_code == 200, f"{path}: {response.text[:200]}"


async def test_a_live_session_is_not_thrown_away(client: httpx.AsyncClient) -> None:
    """The check must not cost a student their uploads on every request.

    A validating `_session` that could not tell "gone" from "unreachable" would mint a
    new workspace whenever the Backend hiccuped, which is a worse bug than the one it
    replaced — the 500 at least kept the documents.
    """
    await client.post("/session")
    first = client.cookies.get("axis_session")
    assert first

    await client.get("/")
    await client.post(
        "/ask", data={"question": "Anything at all?", "strategy": "naive_rag"}
    )

    assert client.cookies.get("axis_session") == first
