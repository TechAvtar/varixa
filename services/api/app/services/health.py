"""Readiness checks: database, object storage, and which engines/providers are configured.

Only non-sensitive facts leave this module: statuses, provider *names* and uptime.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.providers.storage.base import ObjectStorage
from app.utils.metrics import registry

CheckStatus = Literal["ok", "unavailable"]


@dataclass(frozen=True)
class HealthReport:
    database: CheckStatus
    storage: CheckStatus
    providers: dict[str, str]
    uptime_seconds: float

    @property
    def status(self) -> Literal["ok", "degraded"]:
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


async def readiness(
    session: AsyncSession, storage: ObjectStorage, settings: Settings
) -> HealthReport:
    return HealthReport(
        database=await check_database(session),
        storage=await check_storage(storage),
        providers=configured_providers(settings),
        uptime_seconds=round(registry.uptime_seconds, 3),
    )
