import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SynthesisCitation(BaseModel):
    """An evidence record the model relied on, resolved so the reader can check it."""

    id: uuid.UUID
    rule: str
    level: str
    claim: str


class SynthesisSectionResponse(BaseModel):
    key: str
    question: str
    text: str
    citations: list[SynthesisCitation]
    grounded: bool
    dropped_citations: int


class SynthesisResponse(BaseModel):
    provider: str
    model: str
    model_version: str
    prompt_version: str
    generated_at: datetime
    # False when the evidence changed after this synthesis was produced.
    current: bool
    grounded: bool
    warnings: list[str]
    sections: list[SynthesisSectionResponse]
    cached: bool
    latency_ms: int | None
    tokens_in: int | None
    tokens_out: int | None
    estimated_cost: float | None
    limitations: list[str]
    raw: dict[str, Any]
