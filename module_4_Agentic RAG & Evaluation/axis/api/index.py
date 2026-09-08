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

from axis.asgi import app  # noqa: E402

__all__ = ["app"]
