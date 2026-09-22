from typing import Any

from pydantic import BaseModel, Field

MAX_TITLE_LENGTH = 300


class TextAnalysisCreate(BaseModel):
    text: str = Field(min_length=1)
    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH)


class LanguageResponse(BaseModel):
    language: str | None
    confidence: float | None
    candidates: list[dict[str, Any]]
    engine: str
    reason: str | None


class TextAnalysisResponse(BaseModel):
    original_excerpt: str
    normalized_excerpt: str
    excerpt_chars: int
    truncated: bool
    original_sha256: str | None
    normalized_sha256: str
    normalization: dict[str, Any]
    language: LanguageResponse | None
    statistics: dict[str, Any]
    structure: dict[str, Any]
    limitations: list[str]
