from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.evidence import EvidenceRecordResponse
from app.schemas.synthesis import SynthesisResponse


class OverviewStep(BaseModel):
    name: str
    status: str
    duration_ms: int | None
    error_code: str | None


class OverviewEngine(BaseModel):
    """One provider/version pair that contributed, with its audited call counts."""

    provider: str
    model_version: str | None
    operations: list[str]
    calls: int
    cached: int
    failed: int


class OverviewMethodology(BaseModel):
    level_definitions: dict[str, str]
    notes: list[str]
    steps: list[OverviewStep]
    engines: list[OverviewEngine]
    thresholds: dict[str, Any]


class OverviewResponse(BaseModel):
    """The report's first page: grouped evidence, synthesis and methodology, from stored rows."""

    version: str
    generated_at: datetime
    counts: dict[str, int]
    synthesis_confidence: float
    verified: list[EvidenceRecordResponse]
    strong: list[EvidenceRecordResponse]
    probabilistic: list[EvidenceRecordResponse]
    conflicts: list[EvidenceRecordResponse]
    unknown: list[EvidenceRecordResponse]
    synthesis: SynthesisResponse | None
    methodology: OverviewMethodology
