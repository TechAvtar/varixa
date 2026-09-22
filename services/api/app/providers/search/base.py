"""Source / reverse-search interfaces.

A match is *evidence of similarity or discovery*, never proof of origin: a
reverse-image hit shows where similar content was found, not where it came
from; a phrase hit shows shared wording, not plagiarism. Adapters translate
vendor results into ``SourceMatch`` without leaking vendor-specific fields.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

SourceKind = Literal["web_page", "image", "document", "social", "unknown"]


class SourceSearchError(Exception):
    """The provider was called but failed (network, auth, quota, bad payload)."""


@dataclass(frozen=True)
class SourceMatch:
    provider: str
    url: str
    title: str | None
    snippet: str | None
    # Provider relevance/similarity in 0-1 when available; not comparable across providers.
    similarity: float | None
    source_kind: SourceKind
    # For text: the phrase that was queried and matched.
    matched_phrase: str | None
    # Publication/first-seen date as reported by the provider, if any (ISO string).
    published_at: str | None
    discovered_at: datetime
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchResult:
    provider: str
    provider_version: str
    modality: Literal["image", "text"]
    matches: list[SourceMatch]
    queried_phrases: list[str] = field(default_factory=list)
    latency_ms: int | None = None
    request_id: str | None = None
    cached: bool = False
    estimated_cost: float | None = None
    limitations: list[str] = field(default_factory=list)


class ImageSourceSearch(Protocol):
    name: str

    async def search_image(self, content: bytes, *, metadata: dict[str, Any]) -> SearchResult: ...


class TextSourceSearch(Protocol):
    name: str

    async def search_text(self, text: str, *, phrases: list[str]) -> SearchResult: ...


GENERIC_LIMITATIONS = [
    "A source match shows where similar content was found, not where it originated or "
    "which copy came first.",
    "Coverage is limited to what the search provider has indexed; absence of matches is not "
    "evidence that the content is original.",
]
