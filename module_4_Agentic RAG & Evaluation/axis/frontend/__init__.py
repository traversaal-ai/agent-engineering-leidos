"""Axis Frontend — server-rendered UI (Jinja2 + HTMX).

Talks to the Backend over HTTP and to nothing else. It does not import `backend`
or `ai_backend` behaviour, which is enforced by
`tests/unit/test_layer_boundaries.py` — so no secret, provider, or retriever is
reachable from this layer regardless of what a template later grows.
"""
