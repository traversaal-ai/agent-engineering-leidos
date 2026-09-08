"""Vercel entrypoint: the same ASGI app, with nothing written to disk.

Vercel bundles this file as a serverless function and serves `axis.asgi:app` from
it. The application is unmodified — what changes is where its state lives, and
that is configured here rather than in the code, because it is a property of this
deployment and not of Axis.

**`:memory:` is doing three jobs at once**, which is why it is the only setting
that has to be right:

1. It is the SQLite path, so sessions, documents and the whole step trace live in
   the instance's memory. A serverless filesystem is read-only apart from `/tmp`,
   and `/tmp` is per-instance and erased between cold starts either way, so there
   is nothing to be gained by writing there.
2. `_build_vector_store` reads it as the signal for a throwaway process and
   returns `InMemoryVectorStore` — pure-Python cosine over a list — instead of
   Chroma. That is what keeps `chromadb` out of the bundle; see
   `requirements.txt`.
3. Both halves of the state then have the same lifetime, which is the property
   that matters. A vector index that outlived the document table would answer
   from chunks whose documents no longer exist.

**What this costs, stated plainly.** State is per-instance and does not survive a
cold start. A student loads the demo corpus, asks questions and reads their trace
within one warm instance; if Vercel starts another, that student begins again
with an empty index. Nothing is corrupted and nothing is shared between students
who should not share — the failure mode is "the board is empty", not "the board
is wrong". Durable, shared state across instances is a Postgres-shaped change,
and the single-machine deployment in `python -m axis` remains the one that keeps
uploads and traces for a whole session.

`setdefault`, so a Vercel environment variable still wins over every line here.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The bundle's root is not necessarily the working directory, and `axis`,
# `frontend`, `backend` and `ai_backend` are all imported as top-level packages.
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# See the docstring: one value, three consequences.
os.environ.setdefault("AXIS_STORAGE__DB_PATH", ":memory:")

# On by default here, unlike locally. The corpus is what there is to demonstrate on
# a URL someone was sent — with it off, a visitor arrives at an empty board and the
# labelled example questions, which are derived from the golden set for this corpus,
# are not offered either. The four paid embedding round trips it costs are charged
# once per instance rather than once per click.
os.environ.setdefault("AXIS_DEMO__DOCUMENTS_ENABLED", "true")

from axis.asgi import app as _app  # noqa: E402


ACCESS_COOKIE = "axis_access"
ACCESS_PATH = "/access"


def _access_token(secret: str) -> str:
    """A signature of the password, never the password itself.

    Same reasoning as Alex's gate in `module_3_Enterprise RAG/backend/gate.py`: a
    cookie is readable by anything that can reach the browser's jar, and one that
    contained the shared password would hand it over intact. This is derived from it
    and cannot be turned back into it.
    """
    import hashlib
    import hmac

    return hmac.new(secret.encode(), b"axis-access-v1", hashlib.sha256).hexdigest()


def _login_page(error: str = "") -> bytes:
    """The screen in front of everything. One field, no navigation, no app behind it.

    Self-contained — its own inline CSS, no `/static` — because the gate has to render
    before any asset request is allowed through, and a login screen that depends on the
    thing it is protecting is a login screen that renders unstyled.
    """
    message = (
        '<p class="error">Incorrect password.</p>' if error else
        '<p class="hint">This deployment runs on live API keys.</p>'
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Axis</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin:0; min-height:100vh; display:grid; place-items:center;
         font:400 15px/1.5 ui-sans-serif,system-ui,-apple-system,sans-serif;
         background:#0f1115; color:#e7e9ee; }}
  .card {{ width:min(92vw,22rem); padding:2rem; border:1px solid #262a33;
          border-radius:12px; background:#151821; }}
  .mark {{ font-weight:600; letter-spacing:.02em; margin:0 0 .25rem; }}
  .lede {{ margin:0 0 1.5rem; color:#9aa3b2; font-size:.9rem; }}
  label {{ display:block; font-size:.82rem; color:#9aa3b2; margin:0 0 .4rem; }}
  input {{ width:100%; box-sizing:border-box; padding:.6rem .7rem; font-size:1rem;
          border:1px solid #2d323d; border-radius:8px; background:#0f1115;
          color:#e7e9ee; }}
  input:focus {{ outline:2px solid #4c7dff; outline-offset:1px; }}
  button {{ margin-top:1rem; width:100%; padding:.6rem; font-size:.95rem;
           font-weight:500; border:0; border-radius:8px; background:#4c7dff;
           color:#fff; cursor:pointer; }}
  .error {{ margin:0 0 1rem; color:#ff8f8f; font-size:.85rem; }}
  .hint {{ margin:0 0 1rem; color:#6f7787; font-size:.8rem; }}
</style></head>
<body>
  <form class="card" method="post" action="{ACCESS_PATH}">
    <p class="mark">&#9670; Axis</p>
    <p class="lede">Naive RAG and Agentic RAG, measured side by side.</p>
    {message}
    <label for="p">Password</label>
    <input id="p" name="password" type="password" autofocus autocomplete="current-password">
    <button type="submit">Enter</button>
  </form>
</body></html>""".encode("utf-8")


def _gate(inner):
    """One shared password, as a screen in front of the whole deployment.

    **Not Vercel's own password protection**, which is the obvious place for this and
    is gated behind the Advanced Deployment Protection add-on the team does not have —
    the API answers `428 invalid_password_protection`. The other built-in, Vercel
    Authentication, needs every visitor to hold a Vercel account with access to the
    team, which a room of students does not.

    **And not HTTP Basic**, which is three lines shorter and asks for a username nobody
    has. What a class needs is what Alex already does: a page that says *enter
    password*, one field, and the product behind it.

    Everything is behind it — pages, `/api/v1`, the static assets — so there is no
    order of requests that reaches the app without the cookie. Off unless
    `AXIS_ACCESS_PASSWORD` is set, so `python -m axis` on a laptop is unchanged and a
    misconfigured deployment fails open rather than locking an instructor out
    mid-class.
    """
    secret = os.environ.get("AXIS_ACCESS_PASSWORD", "")
    if not secret:
        return inner

    import hmac
    from urllib.parse import parse_qs

    token = _access_token(secret)

    async def guarded(scope, receive, send):
        if scope["type"] != "http":
            await inner(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        cookies = headers.get(b"cookie", b"").decode("latin-1")
        offered = ""
        for part in cookies.split(";"):
            name, _, value = part.strip().partition("=")
            if name == ACCESS_COOKIE:
                offered = value
                break

        if hmac.compare_digest(offered, token):
            await inner(scope, receive, send)
            return

        async def reply(status, body, extra_headers=()):
            await send(
                {
                    "type": "http.response.start",
                    "status": status,
                    "headers": [
                        (b"content-type", b"text/html; charset=utf-8"),
                        (b"content-length", str(len(body)).encode()),
                        (b"cache-control", b"no-store"),
                        *extra_headers,
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})

        if scope["method"] == "POST" and scope["path"] == ACCESS_PATH:
            raw = b""
            while True:
                message = await receive()
                raw += message.get("body", b"")
                if not message.get("more_body"):
                    break
            given = parse_qs(raw.decode("utf-8", "replace")).get("password", [""])[0]
            if hmac.compare_digest(given.strip(), secret):
                # `secure` because the only deployment this runs on is HTTPS, and the
                # cookie is the whole gate. Twelve hours: longer than a class, shorter
                # than a shared laptop is left unattended.
                cookie = (
                    f"{ACCESS_COOKIE}={token}; Path=/; HttpOnly; Secure; "
                    "SameSite=Lax; Max-Age=43200"
                ).encode()
                body = b""
                await send(
                    {
                        "type": "http.response.start",
                        "status": 303,
                        "headers": [
                            (b"location", b"/"),
                            (b"set-cookie", cookie),
                            (b"content-length", b"0"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
            await reply(401, _login_page(error="1"))
            return

        # Everything else, whatever the method or path, is the screen. 401 rather than
        # 200 so a script or a probe is told plainly that this is not the app.
        await reply(401, _login_page())

    return guarded


app = _gate(_app)

__all__ = ["app"]
