"""Translating Axis errors into HTTP responses.

The only place in the system that knows both about `AxisError` and about status
codes. Nothing in `ai_backend/` imports FastAPI, and nothing there raises an
`HTTPException` — that separation is what lets the AI Backend be driven from a
script or a notebook, and it is checked by
`tests/unit/test_layer_boundaries.py`.

Every response carries a stable machine-readable `code`. The Frontend renders
`budget_exceeded` differently from `provider_error` (Section 11 wants a cap to
read as "stopped, budget reached", not as a crash), and it should not have to
pattern-match on English prose to tell them apart.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ai_backend.errors import (
    AxisError,
    BudgetExceededError,
    ConfigurationError,
    IngestionError,
    ProviderError,
    ProviderRateLimitError,
    RetrievalUnavailableError,
    UnsupportedStrategyError,
)

logger = logging.getLogger("axis.backend")


class AuthError(AxisError):
    code = "unauthorized"


class UploadLimitError(AxisError):
    code = "upload_limit_reached"


class ValidationError(AxisError):
    code = "invalid_request"


class NotFoundError(AxisError):
    code = "not_found"


# Deliberately explicit rather than derived from the class hierarchy: reading
# which failure becomes which status code matters more here than avoiding a few
# lines of repetition.
_STATUS: dict[type[AxisError], int] = {
    AuthError: status.HTTP_401_UNAUTHORIZED,
    ValidationError: status.HTTP_400_BAD_REQUEST,
    NotFoundError: status.HTTP_404_NOT_FOUND,
    # 413, not 400: the request was well-formed, there is simply no room for it.
    UploadLimitError: status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    # 429 so that an automated client backs off, and so a cap reads as a limit
    # rather than as a malformed request.
    BudgetExceededError: status.HTTP_429_TOO_MANY_REQUESTS,
    ProviderRateLimitError: status.HTTP_429_TOO_MANY_REQUESTS,
    # 502: the fault is upstream of us, and saying so points the student at the
    # provider rather than at their own question.
    ProviderError: status.HTTP_502_BAD_GATEWAY,
    IngestionError: status.HTTP_422_UNPROCESSABLE_ENTITY,
    # 409: the strategy exists but its index does not. Explicitly *not* handled
    # by silently substituting the other retriever.
    RetrievalUnavailableError: status.HTTP_409_CONFLICT,
    UnsupportedStrategyError: status.HTTP_501_NOT_IMPLEMENTED,
    ConfigurationError: status.HTTP_500_INTERNAL_SERVER_ERROR,
}


def status_for(exc: AxisError) -> int:
    # Walk the MRO so a subclass added later inherits a sensible code without
    # having to be registered here.
    for klass in type(exc).__mro__:
        if klass in _STATUS:
            return _STATUS[klass]  # type: ignore[index]
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def _body(exc: AxisError) -> dict[str, object]:
    payload: dict[str, object] = {"code": exc.code, "message": exc.message}
    if exc.detail:
        payload["detail"] = exc.detail
    return payload


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AxisError)
    async def _axis_error(request: Request, exc: AxisError) -> JSONResponse:
        code = status_for(exc)
        # A stack trace only for genuine faults. A designed refusal gets one line
        # however it maps to HTTP — "your provider cannot call tools, so the agentic
        # strategy is unavailable" is a 501 with a stated fix, and tracebacking it
        # would bury real faults in a workshop's logs under noise.
        if code >= 500 and not exc.is_expected:
            logger.exception("Unhandled Axis error on %s", request.url.path)
        else:
            logger.info("%s on %s: %s", exc.code, request.url.path, exc.message)
        return JSONResponse(status_code=code, content=_body(exc))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Reshaped into the same envelope as everything else so the Frontend has
        # one error format to render rather than two.
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "code": "invalid_request",
                "message": "The request could not be validated.",
                "detail": str(exc.errors()),
            },
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unexpected error on %s", request.url.path)
        # No exception text in the body. An unexpected error can carry anything,
        # including a fragment of a provider response or a file path, and this
        # response may be projected on a classroom wall.
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "code": "internal_error",
                "message": "Something went wrong inside Axis. Check the server logs.",
            },
        )
