import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.enums import ProviderCallStatus


class ProviderCallResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    operation: str
    model_version: str | None
    request_id: str | None
    status: ProviderCallStatus
    latency_ms: int | None
    estimated_cost: float | None
    request_hash: str | None
    response_json: dict[str, Any] | None
    error_json: dict[str, Any] | None
    created_at: datetime


class ProviderCallsResponse(BaseModel):
    calls: list[ProviderCallResponse]
    total_estimated_cost: float
    currency: str = "USD"
