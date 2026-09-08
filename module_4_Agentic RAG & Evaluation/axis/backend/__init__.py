"""Axis Backend — the application layer.

Sessions, auth, upload validation, rate limits, cost caps, persistence, and
dispatch. Contains no retrieval or generation logic: it dispatches to the AI
Backend but does not know how an answer is produced (System Design Section 6.1).

That boundary is enforced mechanically, not by convention. `backend/dispatch.py`
is the only module here permitted to import AI Backend behaviour, and
`tests/unit/test_layer_boundaries.py` fails the build if another one does.

In a multi-instance deployment the auth, rate-limiting, and validation
responsibilities in `core/` would move to a real API gateway. Here the Backend
plays that role directly — worth teaching as a concept even though the component
is deliberately absent (Section 6.3).
"""
