"""Aggregates the v1 routes.

Route paths here are relative — the app is mounted at `/api/v1` by
`axis/asgi.py`, which is what produces the surface documented in System Design
Section 6.6. Keeping the prefix in the mount rather than repeating it on every
router means the documented API surface has exactly one definition.
"""

from fastapi import APIRouter

from backend.api.v1 import (
    compare,
    demo,
    documents,
    health,
    query,
    sessions,
    summarize,
    trace,
)

api_router = APIRouter()

# Health first: it is the only route with no auth and no session, and it is what
# the Milestone -1 acceptance test exercises.
api_router.include_router(health.router)
# The other unauthenticated route, and for a stated reason — see demo.py. Kept next
# to health so the no-auth surface is two adjacent lines rather than something a
# reader has to go looking for.
api_router.include_router(demo.router)
api_router.include_router(sessions.router)
api_router.include_router(documents.router)
api_router.include_router(query.router)
api_router.include_router(summarize.router)
api_router.include_router(trace.router)
api_router.include_router(compare.router)

__all__ = ["api_router"]
