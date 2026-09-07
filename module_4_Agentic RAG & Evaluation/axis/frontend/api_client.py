"""The Frontend's only route to the Backend.

This module is the reason the Frontend/Backend split is real rather than
decorative. It speaks HTTP. It does not import `backend` or `ai_backend` — a
check `tests/unit/test_layer_boundaries.py` enforces — so the Frontend physically
cannot reach a provider, a retriever, or a secret, whatever anyone later adds to
a template.

`transport` is injectable so tests can point it at the composed ASGI app instead
of a socket. That keeps real HTTP semantics — serialisation, status codes, headers,
the SSE framing — while letting the suite run with no listening port.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

# Through the same door `Strategy` comes through — `ai_backend.contracts` is shared
# vocabulary, and `test_layer_boundaries` allows it for exactly this: a name both
# layers have to agree on, carrying no behaviour and no way to reach a provider.
# Re-deriving the corpus names here would be two lists to keep in step, and the one
# that drifted would send a browser's corpus to a scope the Backend never defined.
from ai_backend.contracts.pipeline import DEFAULT_CORPUS


class BackendClient:
    """A thin, typed-enough wrapper over the Backend's REST surface."""

    def __init__(
        self,
        *,
        base_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        # Generous: an agentic query with a multi-hop chain legitimately takes tens of
        # seconds, and a Compare run targets 45. A tight timeout here would surface as a
        # broken UI for a system that was working correctly.
        self._timeout = timeout_seconds

    def _client(self, token: str | None = None) -> httpx.AsyncClient:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return httpx.AsyncClient(
            base_url=self._base_url,
            transport=self._transport,
            timeout=self._timeout,
            headers=headers,
        )

    async def health(self, *, deep: bool = False) -> dict[str, Any]:
        async with self._client() as client:
            response = await client.get("/health", params={"deep": deep})
            response.raise_for_status()
            return response.json()

    async def create_session(self) -> dict[str, Any]:
        async with self._client() as client:
            response = await client.post("/sessions", json={})
            response.raise_for_status()
            return response.json()

    async def get_session(self, session_id: str, *, token: str) -> dict[str, Any]:
        async with self._client(token) as client:
            response = await client.get(f"/sessions/{session_id}")
            response.raise_for_status()
            return response.json()

    async def query(
        self,
        session_id: str,
        *,
        token: str,
        question: str,
        strategy: str,
        pace_ms: int = 0,
        web_search: bool = False,
        cache: bool = True,
        corpus: str = DEFAULT_CORPUS,
    ) -> httpx.Response:
        """Submit a question.

        Returns the raw `Response` rather than parsed JSON so the caller can
        render a 429 (cap reached) or a 501 (strategy unavailable as configured) as
        the distinct, meaningful states they are. Raising on status here would flatten
        them into one generic failure — losing exactly the information Section 11
        wants shown.
        """
        async with self._client(token) as client:
            return await client.post(
                f"/sessions/{session_id}/query",
                json={
                    "question": question,
                    "strategy": strategy,
                    "pace_ms": pace_ms,
                    # Permission for this one query. The Backend combines it with
                    # whether a provider is configured at all, so `True` here on an
                    # install with `AXIS_SEARCH__PROVIDER=none` reaches nothing.
                    "web_search": web_search,
                    # Also permission, and also combined server-side with whether a
                    # cache exists at all (`AXIS_CACHE__ENABLED`).
                    "cache": cache,
                    # Which corpus to search. Carried on the request rather than read
                    # from the cookie server-side, because Compare and the pain-point
                    # runs need to name one explicitly too.
                    "corpus": corpus,
                },
            )

    async def start_new_conversation(self, session_id: str, *, token: str) -> None:
        """Forget the conversation, keeping the documents and the run history.

        A `DELETE` on the turns rather than on the session: the index and the run
        list both survive, which is the whole distinction — see the Backend route.
        """
        async with self._client(token) as client:
            response = await client.delete(f"/sessions/{session_id}/turns")
            response.raise_for_status()

    async def upload(
        self,
        session_id: str,
        *,
        token: str,
        files: list[tuple[str, tuple]],
        pace_ms: int = 0,
        corpus: str = DEFAULT_CORPUS,
    ) -> httpx.Response:
        """Forward an upload. Returns the raw response.

        Unparsed, because per-file failures come back with HTTP 200 and a body
        describing which file failed and why — raising on status would collapse
        "four of five indexed" into a generic error.
        """
        async with self._client(token) as client:
            return await client.post(
                f"/sessions/{session_id}/documents",
                files=files,
                data={"pace_ms": str(pace_ms), "corpus": corpus},
            )

    async def load_demo_documents(
        self, session_id: str, *, token: str, pace_ms: int = 0
    ) -> httpx.Response:
        """Index the demo corpus. Returns the raw response.

        Unparsed for the same reason `upload` is: per-file outcomes come back with
        HTTP 200, and a full session comes back 413 with a message worth showing.
        """
        async with self._client(token) as client:
            return await client.post(
                f"/sessions/{session_id}/documents/demo",
                data={"pace_ms": str(pace_ms)},
            )

    async def demo_questions(self) -> dict[str, Any]:
        """The labelled question set, and the corpus it was measured against.

        Both, because a prediction is a claim about specific documents and the caller
        has to be able to tell whether those documents are indexed before offering it.

        Failures are the caller's to absorb: a page that cannot draw four example
        questions should still draw everything else, so `frontend/app.py` treats an
        error here as an empty set rather than a broken render.
        """
        async with self._client() as client:
            response = await client.get("/demo/questions")
            response.raise_for_status()
            body = response.json()
            return {
                "questions": body.get("questions") or [],
                "documents": body.get("documents") or [],
            }

    async def pain_points(self) -> dict[str, Any]:
        """The four pain points, and the corpus their demonstrations need.

        Same shape and same reasoning as `demo_questions` above: both halves,
        because a demonstration is a claim about specific documents and the caller
        has to know whether they are indexed before offering to run it.
        """
        async with self._client() as client:
            response = await client.get("/demo/pain-points")
            response.raise_for_status()
            body = response.json()
            return {
                "pain_points": body.get("pain_points") or [],
                "documents": body.get("documents") or [],
            }

    async def summarize(
        self,
        session_id: str,
        *,
        token: str,
        document_ids: list[str] | None = None,
        corpus: str = DEFAULT_CORPUS,
    ) -> httpx.Response:
        """Ask for an overview of the indexed documents. Returns the raw response.

        Unparsed like `query`, so a 429 (cap reached) stays a distinct, meaningful
        state — summarization is the most expensive action available and therefore the
        one most likely to hit the cap.

        `document_ids` is the Summarize page's checkboxes. `None` means everything —
        everything *in this corpus*, which is what keeps the page's cost curve honest.
        A body is always sent now, because the corpus has to travel; `document_ids` is
        omitted from it rather than sent as null, so the "no selection means all"
        reading a bare POST has always had is unchanged.
        """
        body: dict[str, Any] = {"corpus": corpus}
        if document_ids is not None:
            body["document_ids"] = document_ids
        async with self._client(token) as client:
            return await client.post(f"/sessions/{session_id}/summarize", json=body)

    async def documents(
        self, session_id: str, *, token: str, corpus: str | None = None
    ) -> list[dict[str, Any]]:
        """This session's documents — one corpus's, or every corpus's.

        `corpus=None` lists everything, which the rail's per-corpus counts want.
        Naming one lists only what the active index can actually reach.
        """
        params = {"corpus": corpus} if corpus else None
        async with self._client(token) as client:
            response = await client.get(
                f"/sessions/{session_id}/documents", params=params
            )
            response.raise_for_status()
            return response.json()

    async def clear_corpus(self, session_id: str, *, token: str, corpus: str) -> None:
        """Empty one corpus so it can be filled again. Failures are swallowed.

        Swallowed like `delete_session`'s, and for a weaker version of the same reason:
        the page is about to re-render from the Backend's own state, so a failure here
        shows up as the corpus still holding its documents — visible and retryable —
        rather than as a 500 in front of a class.
        """
        try:
            async with self._client(token) as client:
                await client.delete(f"/sessions/{session_id}/corpus/{corpus}")
        except httpx.HTTPError:
            return

    async def trace_steps(
        self, session_id: str, *, token: str, trace_id: str | None = None
    ) -> list[dict[str, Any]]:
        params = {"trace_id": trace_id} if trace_id else None
        async with self._client(token) as client:
            response = await client.get(
                f"/sessions/{session_id}/trace/steps", params=params
            )
            response.raise_for_status()
            return response.json()

    async def delete_session(self, session_id: str, *, token: str) -> None:
        """Discard the session's vector index. Failures are swallowed.

        The caller is about to mint a new session, at which point the old index is
        unreachable whether or not this succeeded — so a failure here leaks storage
        and nothing else, and must not stop a student starting over.
        """
        try:
            async with self._client(token) as client:
                await client.delete(f"/sessions/{session_id}")
        except httpx.HTTPError:
            return

    async def narrate(
        self, session_id: str, *, token: str, step_id: str
    ) -> dict[str, Any]:
        """Generate (or fetch the cached) plain-language explanation of one step."""
        async with self._client(token) as client:
            response = await client.post(
                f"/sessions/{session_id}/trace/{step_id}/narrate"
            )
            response.raise_for_status()
            return response.json()

    # There is no `trace_step` here, and the absence is deliberate rather than an
    # omission: `GET /sessions/{id}/trace/steps/{step_id}` exists and is tested, but the
    # canvas needs the whole trace anyway — it draws every stage of both phases at once
    # — so fetching one step separately would be a second round trip for data already in
    # hand, and a second place for "which step ran this stage?" to be decided. That
    # question has one answer, in `_bind_stages`.

    async def stream_trace(
        self, session_id: str, *, token: str, since_seq: int = 0
    ) -> AsyncIterator[str]:
        """Proxy the SSE trace stream, yielding raw SSE lines.

        **Not used by the current topology, and cannot be.** When the Frontend is
        constructed with an `httpx.ASGITransport` — which is how `axis/asgi.py` wires
        it in-process — the transport buffers a response body to completion, so an
        open-ended stream never yields a line. Verified, not assumed: this generator
        works correctly against a real socket and returns nothing through
        `ASGITransport`.

        Kept because it is right for the topology System Design Section 6.2 describes
        as the alternative, where the Frontend and Backend are separate services and
        this is a real network call. The live canvas polls `/trace/recent` instead —
        see the note there.

        `since_seq` skips replaying steps the caller already has, so a second
        question shows its own run rather than the whole session's history.
        """
        params = {"since_seq": since_seq} if since_seq else None
        async with (
            self._client(token) as client,
            client.stream(
                "GET", f"/sessions/{session_id}/trace", params=params
            ) as response,
        ):
            response.raise_for_status()
            async for line in response.aiter_lines():
                yield line
