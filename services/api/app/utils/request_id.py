"""Per-request correlation ID: honoured from ``X-Request-ID`` or generated."""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

HEADER = "X-Request-ID"
_MAX_LEN = 128


def get_request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    return rid if isinstance(rid, str) else ""


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(HEADER, "")
        rid = incoming if 0 < len(incoming) <= _MAX_LEN and incoming.isprintable() else ""
        request.state.request_id = rid or str(uuid.uuid4())
        response = await call_next(request)
        response.headers[HEADER] = request.state.request_id
        return response
