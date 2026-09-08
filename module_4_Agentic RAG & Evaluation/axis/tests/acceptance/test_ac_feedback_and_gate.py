"""Reporting a wrong answer, and the password screen in front of the deployment.

Two features that arrived together and are unrelated except in when they shipped.
Both are here rather than in a unit file because what matters about each is the
behaviour over HTTP: a control that renders but posts nowhere, and a gate that is
installed but lets a path through, both pass every unit test you could write.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

import httpx
import pytest

from tests.docfixtures import make_pdf

# Milestone 4. Neither feature adds retrieval or generation capability; both are
# what the product needed the first time it was put on a URL somebody else could
# open, which is where this milestone ended up.
pytestmark = pytest.mark.milestone(4)

REPO_ROOT = Path(__file__).resolve().parents[2]


# -- reporting an answer -----------------------------------------------------


_CONTRACT = (
    "Payment terms. Invoices are submitted monthly and payment is due Net 45 "
    "from receipt of a correct invoice. Disputed invoices must be contested in "
    "writing within fifteen business days."
)


async def _answered(client: httpx.AsyncClient) -> httpx.Response:
    """A real run behind a real answer, through the forms a student uses.

    The control being tested renders on an answer, so a test that asks without
    indexing anything asserts against a page that legitimately has no answer on it.
    """
    await client.post(
        "/upload",
        files=[("files", ("contract.pdf", make_pdf(_CONTRACT), "application/pdf"))],
        follow_redirects=True,
    )
    return await client.post(
        "/ask",
        data={"question": "What are the payment terms?", "strategy": "naive_rag"},
    )



async def test_an_answer_carries_a_way_to_report_it(
    client: httpx.AsyncClient, session: dict[str, object]
) -> None:
    """The control renders on the answer, closed, with the run's id inside it.

    The `trace_id` is the whole reason this is a control on the answer rather than a
    mail link: it turns "the answer was wrong" into a run that can be reopened at
    `/trace?id=…` and read stage by stage.
    """
    response = await _answered(client)

    assert response.status_code == 200
    body = response.text
    assert "answer__feedback" in body
    assert 'name="trace_id"' in body
    # Closed by default — an answer a class is reading must not wear a complaint form.
    assert "<details class=\"answer__feedback\">" in body


async def test_the_reasons_offered_are_the_repairs_they_imply(
    client: httpx.AsyncClient, session: dict[str, object]
) -> None:
    """A closed list, because "it was wrong" does not say where to look.

    Each reason points at a different stage of the run — retrieval missed, retrieval
    was fine and the prose is not supported by it, and so on — so choosing one costs
    the reporter a click and saves the reader the whole trace.
    """
    from frontend.app import FEEDBACK_REASONS

    response = await _answered(client)

    for value, _label in FEEDBACK_REASONS:
        assert f'value="{value}"' in response.text


async def test_a_report_names_the_run_it_is_about(
    client: httpx.AsyncClient,
    session: dict[str, object],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The report reaches a sink, and the sink records which run it was.

    A structured log line is a deliberate floor rather than a finished feature — the
    session store is `:memory:` in the deployment and would lose a table of reports
    with the instance — but a report that does not carry its `trace_id` is not worth
    keeping anywhere.
    """
    with caplog.at_level(logging.WARNING, logger="axis.frontend"):
        response = await client.post(
            "/feedback",
            data={
                "trace_id": "abc123",
                "strategy": "naive_rag",
                "reason": "contradicts",
                "note": "Net 45 is wrong.",
            },
            headers={"Referer": "http://test/"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert "flash=" in response.headers["location"]
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "answer reported as wrong" in logged
    assert "abc123" in logged
    assert "contradicts" in logged


async def test_an_invented_reason_is_recorded_as_unspecified(
    client: httpx.AsyncClient,
    session: dict[str, object],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The list is closed on the server too, not only in the markup.

    A `<select>` constrains a browser and nothing else. Recording whatever was posted
    would let the one field that exists to be read by a person carry anything at all
    into the log a person reads.
    """
    with caplog.at_level(logging.WARNING, logger="axis.frontend"):
        await client.post(
            "/feedback",
            data={"trace_id": "abc123", "reason": "<script>", "note": ""},
            headers={"Referer": "http://test/"},
            follow_redirects=False,
        )

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "reason=unspecified" in logged
    assert "<script>" not in logged


async def test_a_note_cannot_forge_a_second_log_line(
    client: httpx.AsyncClient,
    session: dict[str, object],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`note` is whatever a reporter typed, and it lands in a log a person reads.

    Newlines in it would forge entries; an unbounded one is a denial of service
    against the reader.
    """
    with caplog.at_level(logging.WARNING, logger="axis.frontend"):
        await client.post(
            "/feedback",
            data={
                "trace_id": "abc123",
                "reason": "incomplete",
                "note": "first\nWARNING second forged line " + "x" * 900,
            },
            headers={"Referer": "http://test/"},
            follow_redirects=False,
        )

    logged = "\n".join(r.getMessage() for r in caplog.records)
    note = logged.split("note=")[1]
    # One line — the newline is gone, so the text cannot pose as a second entry —
    # and bounded, so it cannot bury the entries around it.
    assert "\n" not in note
    assert "WARNING" in note, "the words survive; only the line break does not"
    assert len(note) < 560


# -- the password screen -----------------------------------------------------


def _load_entrypoint():
    """`api/index.py` by path: it is a Vercel entrypoint, not an importable package."""
    spec = importlib.util.spec_from_file_location(
        "axis_vercel_entrypoint", REPO_ROOT / "api" / "index.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def entrypoint():
    return _load_entrypoint()


async def _drive(app, method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.request(method, path, **kwargs)


async def _inner(scope, receive, send) -> None:
    """Stands in for the whole application. Reaching it at all is the failure."""
    body = b"THE APP"
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain"), (b"content-length", b"7")],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def test_without_a_password_configured_nothing_is_in_the_way(entrypoint) -> None:
    """Off by default, so `python -m axis` on a laptop is unchanged.

    It also means a deployment that forgot the variable fails *open* rather than
    locking an instructor out in front of a class — the wrong failure to have chosen
    the other way round for a teaching tool.
    """
    import os

    os.environ.pop("AXIS_ACCESS_PASSWORD", None)
    gated = entrypoint._gate(_inner)

    assert gated is _inner


async def test_the_gate_shows_a_screen_rather_than_a_browser_dialog(
    entrypoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A page that says *enter password*, like Alex has. Not HTTP Basic.

    Basic auth is shorter and asks for a username nobody has. What a class needs is
    one field and the product behind it.
    """
    monkeypatch.setenv("AXIS_ACCESS_PASSWORD", "leidos-training")
    gated = entrypoint._gate(_inner)

    response = await _drive(gated, "GET", "/")

    assert response.status_code == 401
    assert "THE APP" not in response.text
    assert 'name="password"' in response.text
    assert "www-authenticate" not in {k.lower() for k in response.headers}


async def test_every_path_is_behind_it_including_the_api(
    entrypoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No order of requests reaches the app without the cookie.

    The API is the half that spends money, so a gate over the pages alone would
    protect the part that costs nothing.
    """
    monkeypatch.setenv("AXIS_ACCESS_PASSWORD", "leidos-training")
    gated = entrypoint._gate(_inner)

    for path in ("/", "/api/v1/health", "/static/app.css", "/ask"):
        response = await _drive(gated, "GET", path)
        assert response.status_code == 401, path
        assert "THE APP" not in response.text, path


async def test_the_wrong_password_says_so_and_grants_nothing(
    entrypoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AXIS_ACCESS_PASSWORD", "leidos-training")
    gated = entrypoint._gate(_inner)

    response = await _drive(gated, "POST", "/access", data={"password": "wrong"})

    assert response.status_code == 401
    assert "Incorrect password." in response.text
    assert "set-cookie" not in {k.lower() for k in response.headers}


async def test_the_right_password_mints_a_cookie_that_is_not_the_password(
    entrypoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Signed, so a cookie read out of a browser does not hand over the password.

    The same reasoning as Alex's gate, which this follows deliberately.
    """
    monkeypatch.setenv("AXIS_ACCESS_PASSWORD", "leidos-training")
    gated = entrypoint._gate(_inner)

    response = await _drive(
        gated, "POST", "/access", data={"password": "leidos-training"}
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookie = response.headers["set-cookie"]
    assert "leidos-training" not in cookie
    assert "HttpOnly" in cookie and "Secure" in cookie

    # And it opens the door.
    token = cookie.split("=", 1)[1].split(";", 1)[0]
    allowed = await _drive(
        gated, "GET", "/", headers={"Cookie": f"{entrypoint.ACCESS_COOKIE}={token}"}
    )
    assert allowed.status_code == 200
    assert "THE APP" in allowed.text
