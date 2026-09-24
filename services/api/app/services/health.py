"""Readiness checks: database, object storage, and which engines/providers are configured.

Only non-sensitive facts leave this module: statuses, provider *names*, engine versions
and uptime. Never a path, a key or an endpoint.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.providers.provenance import C2paToolInspector, build_provenance_inspector, trust_summary
from app.providers.storage.base import ObjectStorage
from app.utils.metrics import registry

CheckStatus = Literal["ok", "unavailable"]
EngineStatus = Literal["ok", "unavailable", "not_configured"]

_ENGINE_PROBE_TIMEOUT = 2.0
_ENGINE_CACHE_TTL = 60.0
_engine_cache: dict[str, tuple[float, dict[str, Any]]] = {}


@dataclass(frozen=True)
class HealthReport:
    database: CheckStatus
    storage: CheckStatus
    providers: dict[str, str]
    uptime_seconds: float
    # Binary engines the pipeline shells out to: {"c2patool": {"status", "version"}}.
    engines: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def status(self) -> Literal["ok", "degraded"]:
        # An absent optional engine degrades a feature (reported as such), not the service.
        return "ok" if self.database == "ok" and self.storage == "ok" else "degraded"


async def check_database(session: AsyncSession) -> CheckStatus:
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return "unavailable"
    return "ok"


async def check_storage(storage: ObjectStorage) -> CheckStatus:
    try:
        return "ok" if await storage.probe() else "unavailable"
    except Exception:
        return "unavailable"


def configured_providers(settings: Settings) -> dict[str, str]:
    return {
        "metadata": settings.metadata_engine,
        "provenance": settings.provenance_engine,
        "ai_detector": settings.ai_detector_provider,
        "source_search": settings.source_search_provider,
        "llm": settings.llm_provider,
        "storage": settings.storage_backend,
    }


async def check_c2patool(settings: Settings) -> dict[str, Any]:
    """Version of the configured c2patool, cached for a minute; the path never leaves."""
    if settings.provenance_engine == "none":
        return {"status": "not_configured", "version": None, "trust": trust_summary(settings)}
    now = time.monotonic()
    cached = _engine_cache.get("c2patool")
    if cached and now - cached[0] < _ENGINE_CACHE_TTL:
        return cached[1]
    result: dict[str, Any]
    try:
        inspector = build_provenance_inspector(settings)
    except RuntimeError:
        inspector = None
    trust = trust_summary(settings)
    if not isinstance(inspector, C2paToolInspector):
        result = {"status": "unavailable", "version": None, "trust": trust}
    else:
        try:
            version = await asyncio.wait_for(inspector.version(), _ENGINE_PROBE_TIMEOUT)
            result = {"status": "ok", "version": version[:64], "trust": trust}
        except Exception:
            result = {"status": "unavailable", "version": None, "trust": trust}
    _engine_cache["c2patool"] = (now, result)
    return result


async def readiness(
    session: AsyncSession, storage: ObjectStorage, settings: Settings
) -> HealthReport:
    return HealthReport(
        database=await check_database(session),
        storage=await check_storage(storage),
        providers=configured_providers(settings),
        uptime_seconds=round(registry.uptime_seconds, 3),
        engines={"c2patool": await check_c2patool(settings)},
    )
