"""Scheduled maintenance entry points for hosts without long-lived processes.

``GET /api/v1/internal/retention`` runs one retention sweep. It exists only when a cron secret
is configured (``VERIXA_CRON_SECRET``, or ``CRON_SECRET`` which Vercel Cron sends as a bearer
token); without one it answers 404 like any unknown path. The response carries counts only.
"""

import hmac
from typing import Any

from fastapi import APIRouter, Request

from app.api.deps import AppSettings
from app.utils.errors import NotFoundError, UnauthorizedError
from app.workers.retention import sweep_once

router = APIRouter(prefix="/internal")


@router.get("/retention", include_in_schema=False)
async def run_retention(request: Request, settings: AppSettings) -> dict[str, Any]:
    secret = settings.cron_secret.get_secret_value() if settings.cron_secret else ""
    if not secret:
        raise NotFoundError("Not found.")
    scheme, _, presented = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(presented.strip(), secret):
        raise UnauthorizedError("Cron secret required.", code="CRON_SECRET_REQUIRED")
    report = await sweep_once(
        request.app.state.session_factory, request.app.state.storage, settings
    )
    return report.to_json()
