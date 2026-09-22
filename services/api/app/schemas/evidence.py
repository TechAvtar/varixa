import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.enums import EvidenceLevel

EvidenceKind = Literal["fact", "signal", "unknown", "conflict"]


class EvidenceRecordResponse(BaseModel):
    """One leveled, traceable evidence record (docs/07). ``refs`` point at raw observations."""

    id: uuid.UUID
    rule: str
    category: str
    level: EvidenceLevel
    kind: EvidenceKind
    claim: str
    source: str
    confidence: float | None
    detail: str | None
    limitation: str | None
    refs: list[str]
    provider_version: str | None
    conflicts_with: list[str]
    data: dict[str, Any]
    created_at: datetime


class EvidenceListResponse(BaseModel):
    engine_version: str
    generated_at: datetime
    counts: dict[str, int]
    conflicts: int
    # Strongest leveled record minus a penalty per conflict (docs/07), in [0, 1].
    synthesis_confidence: float
    # Thresholds in force for this deployment (rules are never hard-coded).
    thresholds: dict[str, Any]
    items: list[EvidenceRecordResponse]
