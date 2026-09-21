from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_session
from app.schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> HealthResponse:
    """Liveness + DB readiness probe. Exposes only non-sensitive metadata."""
    try:
        await session.execute(text("SELECT 1"))
        database = "ok"
    except SQLAlchemyError:
        # Connection details are never returned to the client.
        database = "unavailable"
    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        database=database,
    )
