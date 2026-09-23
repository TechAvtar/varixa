from fastapi import APIRouter

from app.api.deps import AppSettings, DbSession, Storage
from app.schemas.health import HealthResponse, LivenessResponse
from app.services.health import readiness

router = APIRouter()


@router.get("/health/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    """Liveness only: the process answers. No dependencies are touched."""
    return LivenessResponse(status="ok")


@router.get("/health", response_model=HealthResponse)
async def health(settings: AppSettings, session: DbSession, storage: Storage) -> HealthResponse:
    """Readiness: database and storage reachable. Exposes only non-sensitive metadata."""
    report = await readiness(session, storage, settings)
    return HealthResponse(
        status=report.status,
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        database=report.database,
        storage=report.storage,
        providers=report.providers,
        uptime_seconds=report.uptime_seconds,
    )
