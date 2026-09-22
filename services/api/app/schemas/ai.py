from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class AIDetectionResponse(BaseModel):
    modality: Literal["image", "text"]
    provider: str
    model: str
    provider_version: str
    score: float | None
    label: Literal["likely_ai", "uncertain", "likely_human", "unavailable"]
    calibrated: bool
    cached: bool
    latency_ms: int | None
    evaluated_at: datetime
    thresholds: dict[str, float]
    # Evidence level implied by the initial rules (docs/07): PROBABLE / POSSIBLE / UNKNOWN.
    evidence_level: Literal["PROBABLE", "POSSIBLE", "UNKNOWN"]
    raw: dict[str, Any]
    limitations: list[str]
