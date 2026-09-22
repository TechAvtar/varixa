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


class SourceMatchesResponse(BaseModel):
    modality: Literal["image", "text"]
    provider: str
    provider_version: str
    searched_at: datetime
    queried_phrases: list[str]
    matches: list[SourceMatchResponse]
    limitations: list[str]
