"""Prometheus-style metrics. Aggregates only; never per-user or per-analysis values.

Disabled with ``VERIXA_METRICS_ENABLED=false`` (404). When ``VERIXA_METRICS_TOKEN`` is set
the scrape must send it as a bearer token; production refuses to serve metrics without one.
"""

import hmac

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from app.api.deps import AppSettings
from app.utils.errors import NotFoundError, UnauthorizedError
from app.utils.metrics import registry

router = APIRouter()

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request, settings: AppSettings) -> PlainTextResponse:
    if not settings.metrics_enabled:
        raise NotFoundError("Not found.")
    expected = settings.metrics_token.get_secret_value() if settings.metrics_token else ""
    if not expected and settings.environment == "production":
        raise NotFoundError("Not found.")  # never expose unauthenticated metrics in production
    if expected:
        auth = request.headers.get("authorization", "")
        scheme, _, presented = auth.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(presented.strip(), expected):
            raise UnauthorizedError("Metrics token required.", code="METRICS_TOKEN_REQUIRED")
    return PlainTextResponse(registry.render(), media_type=CONTENT_TYPE)
