"""Request-scoped middleware: correlation ids and access logging.

CORS is configured in `backend/app.py` rather than here, since FastAPI's own
`CORSMiddleware` covers it — restricted to the Frontend's origin per System
Design Section 6.5, priority 6.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ai_backend.contracts.models import new_id

logger = logging.getLogger("axis.access")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id and log the outcome.

    The id goes onto `request.state` and into the response header, so a student
    reporting "it broke" can quote one string that ties their browser's failed
    request to a line in the instructor's server log. During a live class that is
    the difference between diagnosing something and guessing.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or new_id()[:12]
        request.state.request_id = request_id

        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - started) * 1000)

        response.headers[REQUEST_ID_HEADER] = request_id
        # Query strings are not logged: a question a student typed can be
        # personal, and the trace store is the intended place for it.
        #
        # ASCII only, for the same reason as the startup banner in
        # `axis/__main__.py`: a Windows console is cp1252, and "→" surfaces there
        # as a literal "→" escape in every access line.
        logger.info(
            "%s %s -> %s (%dms) id=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )
        return response
