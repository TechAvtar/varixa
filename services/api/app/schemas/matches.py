from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class SourceMatchResponse(BaseModel):
    rank: int
    provider: str
    url: str
    title: str | None
    snippet: str | None
    similarity: float | None
    source_kind: str
    matched_phrase: str | None
    published_at: str | None
    discovered_at: datetime
    raw: dict[str, Any]


class SourceMatchesSummary(BaseModel):
    """Deterministic roll-up of the run. Dates are as reported by sources, never inferred."""

    match_count: int
    domains: list[str]
    domain_count: int
    kinds: dict[str, int]
    similarity_min: float | None
    similarity_max: float | None
    dated_count: int
    earliest_published_at: str | None
    earliest_published_url: str | None


class SourceMatchesResponse(BaseModel):
    modality: Literal["image", "text"]
    provider: str
    provider_version: str
    searched_at: datetime
    queried_phrases: list[str]
    matches: list[SourceMatchResponse]
    summary: SourceMatchesSummary
    limitations: list[str]
