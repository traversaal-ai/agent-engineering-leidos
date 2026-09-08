"""Session bearer tokens — issue, validate, expire.

Deliberately minimal, and the minimalism is the curriculum. System Design
Section 6.4 sets out to teach the issue → validate → expire pattern without
building an identity system: no accounts, no passwords, no refresh flow, no RBAC.
`POST /api/v1/sessions` hands back a token, every other route requires it, and it
dies on its TTL.

What that buys, and what it does not, is worth being clear about with students. It
gives each student an isolated workspace and stops one of them reading another's
documents or trace. It is not authentication of a *person* — anyone holding the
token is the session. For a classroom on one machine that is the right trade;
naming it explicitly is what stops it being copied into something that matters.
"""

from __future__ import annotations

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.core.errors import AuthError, NotFoundError
from backend.store.repositories import SessionRecord, SessionRepository

# auto_error=False so a missing header comes through as None and is refused by
# our own handler — that keeps every 401 in the same response envelope as the
# rest of the API instead of FastAPI's default shape.
_scheme = HTTPBearer(auto_error=False)


def get_session_repository(request: Request) -> SessionRepository:
    """Pull the repository off application state.

    Constructed once at startup in `backend/app.py`; resolved here so routes take
    it as a dependency and tests can override it.
    """
    repo = getattr(request.app.state, "sessions", None)
    if repo is None:  # pragma: no cover - would mean the app was misconfigured
        raise RuntimeError(
            "SessionRepository is missing from app.state. It is created during "
            "application startup in backend/app.py."
        )
    return repo


def require_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(_scheme),
    sessions: SessionRepository = Depends(get_session_repository),
) -> SessionRecord:
    """Resolve the caller's session, or refuse the request.

    An expired token and an unknown token get the same message on purpose —
    distinguishing them would let a caller probe which tokens ever existed. The
    hint about creating a session is safe to give either way.
    """
    if credentials is None or not credentials.credentials:
        raise AuthError(
            "This endpoint requires a session token.",
            detail=(
                "Create one with POST /api/v1/sessions, then send it as "
                "'Authorization: Bearer <token>'."
            ),
        )

    record = sessions.get_by_token(credentials.credentials)
    if record is None or record.is_expired:
        raise AuthError(
            "That session token is not valid, or it has expired.",
            detail="Create a new session with POST /api/v1/sessions.",
        )
    return record


def require_matching_session(
    session_id: str,
    session: SessionRecord = Depends(require_session),
) -> SessionRecord:
    """Confirm the token belongs to the session named in the path.

    Without this, a valid token would grant access to *any* session id — which
    is the per-session isolation in PRD Section 3 quietly not existing. Routes
    are shaped as `/sessions/{session_id}/...`, so the check has to be explicit.

    Reported as 404 rather than 403: a caller with a valid token for another
    session should not be able to learn that this one exists.
    """
    if session.id != session_id:
        raise NotFoundError(f"No session {session_id!r} is accessible with this token.")
    return session
