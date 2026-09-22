"""Reverse-image and phrase/source search adapters.

Matches are discovery signals, never proof of origin.
"""

from app.config import Settings
from app.providers.search.base import (
    GENERIC_LIMITATIONS,
    ImageSourceSearch,
    SearchResult,
    SourceKind,
    SourceMatch,
    SourceSearchError,
    TextSourceSearch,
)
from app.providers.search.mock import MockImageSourceSearch, MockTextSourceSearch


def build_image_source_search(settings: Settings) -> ImageSourceSearch | None:
    if settings.source_search_provider == "none":
        return None
    if settings.source_search_provider == "mock":
        return MockImageSourceSearch()
    raise SourceSearchError(f"unknown source search provider '{settings.source_search_provider}'")


def build_text_source_search(settings: Settings) -> TextSourceSearch | None:
    if settings.source_search_provider == "none":
        return None
    if settings.source_search_provider == "mock":
        return MockTextSourceSearch()
    raise SourceSearchError(f"unknown source search provider '{settings.source_search_provider}'")


__all__ = [
    "GENERIC_LIMITATIONS",
    "ImageSourceSearch",
    "MockImageSourceSearch",
    "MockTextSourceSearch",
    "SearchResult",
    "SourceKind",
    "SourceMatch",
    "SourceSearchError",
    "TextSourceSearch",
    "build_image_source_search",
    "build_text_source_search",
]
