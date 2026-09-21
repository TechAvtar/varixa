"""Renders every error in the documented shape and never leaks stack traces.

{"error": {"code": "...", "message": "...", "request_id": "..."}}
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException  # base class: also catches router 404/405

from app.utils.errors import AppError
from app.utils.request_id import get_request_id

log = logging.getLogger("verixa.api")

_HTTP_CODES = {
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "request_id": get_request_id(request)}}
    return JSONResponse(status_code=status_code, content=body, headers=headers)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        msg = first.get("msg", "Invalid request.")
        message = f"{loc}: {msg}" if loc else str(msg)
        return error_response(request, status_code=422, code="VALIDATION_ERROR", message=message)

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        headers = dict(exc.headers) if exc.headers else None
        return error_response(
            request, status_code=exc.status_code, code=code, message=message, headers=headers
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Log with the correlation id only; the client gets a generic message.
        log.exception("unhandled error request_id=%s", get_request_id(request))
        return error_response(
            request,
            status_code=500,
            code="INTERNAL_ERROR",
            message="An unexpected error occurred.",
        )
