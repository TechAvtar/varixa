"""Per-request correlation and observability middleware.

- honours ``X-Request-ID`` from the caller (bounded, printable) or generates one
- exposes it on ``request.state`` and the ``request_id`` log context variable
- returns it in the response header
- writes one structured request log line and records request metrics per response,
  using the *route template* and never the query string (signed URLs live there)
"""

import logging
import time
import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.utils.metrics import registry
from app.utils.observability import request_id_var

HEADER = "X-Request-ID"
_MAX_LEN = 128
_QUIET_PATHS = ("/api/v1/health", "/metrics")

log = logging.getLogger("verixa.http")


def get_request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    return rid if isinstance(rid, str) else ""


def route_template(request: Request) -> str:
    """The matched route's path pattern (``/api/v1/analysis/{analysis_id}``) or ``unmatched``.

    The router leaves the matched route and its path parameters on the scope; substituting
    the parameter values back into the request path yields the template with its prefix,
    which keeps metric labels bounded (no ids, keys or arbitrary paths).
    """
    scope = request.scope
    if scope.get("route") is None:
        return "unmatched"
    template = str(scope.get("path", ""))
    params: dict[str, Any] = scope.get("path_params") or {}
    for name, value in params.items():
        template = template.replace(str(value), "{" + name + "}", 1)
    return template or "unmatched"


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(HEADER, "")
        rid = incoming if 0 < len(incoming) <= _MAX_LEN and incoming.isprintable() else ""
        request.state.request_id = rid or str(uuid.uuid4())
        token = request_id_var.set(request.state.request_id)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers[HEADER] = request.state.request_id
            return response
        finally:
            elapsed = time.perf_counter() - started
            route = route_template(request)
            registry.record_http(method=request.method, route=route, status=status, seconds=elapsed)
            level = logging.DEBUG if request.url.path.startswith(_QUIET_PATHS) else logging.INFO
            log.log(
                level,
                "http request",
                extra={
                    "method": request.method,
                    "route": route,
                    "status": status,
                    "duration_ms": int(elapsed * 1000),
                },
            )
            request_id_var.reset(token)
