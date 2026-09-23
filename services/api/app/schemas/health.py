from typing import Literal

from pydantic import BaseModel


class LivenessResponse(BaseModel):
    status: Literal["ok"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str
    version: str
    environment: str
    database: Literal["ok", "unavailable"]
    storage: Literal["ok", "unavailable"]
    # Configured engine/provider names only (never keys or endpoints).
    providers: dict[str, str]
    uptime_seconds: float
