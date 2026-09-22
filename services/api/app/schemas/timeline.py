import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.enums import EvidenceLevel


class TimelineEventResponse(BaseModel):
    """One recorded time turned into an event; certainty is the level of its evidence."""

    id: uuid.UUID
    event_type: str
    # Null when the recorded time could not be parsed; ``raw_time`` is always kept.
    event_time: datetime | None
    raw_time: str | None
    tz_known: bool
    certainty: EvidenceLevel
    description: str
    source: str
    source_evidence_ids: list[uuid.UUID]
    data: dict[str, Any]


class TimelineResponse(BaseModel):
    version: str
    generated_at: datetime
    events: list[TimelineEventResponse]
    limitations: list[str]
