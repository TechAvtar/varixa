"""Reverse-image and phrase/source search adapters.

Matches are discovery signals, never proof of origin.
"""

from app.config import Settings
from app.providers.cache import ProviderResultCache
from app.providers.search.base import (
    GENERIC_LIMITATIONS,
    ImageSourceSearch,
    SearchResult,
    SourceKind,
    SourceMatch,
    SourceSearchError,
    TextSourceSearch,
)
from app.providers.search.cache import CachedImageSourceSearch, CachedTextSourceSearch
from app.providers.search.mock import MockImageSourceSearch, MockTextSourceSearch


def build_image_source_search(
    settings: Settings, *, cache: ProviderResultCache | None = None
) -> ImageSourceSearch | None:
    if settings.source_search_provider == "none":
        return None
    if settings.source_search_provider == "mock":
        inner: ImageSourceSearch = MockImageSourceSearch()
    else:
        raise SourceSearchError(
            f"unknown source search provider '{settings.source_search_provider}'"
        )
    return CachedImageSourceSearch(inner, cache) if cache is not None else inner


def build_text_source_search(
    settings: Settings, *, cache: ProviderResultCache | None = None
) -> TextSourceSearch | None:
    if settings.source_search_provider == "none":
        return None
    if settings.source_search_provider == "mock":
        inner: TextSourceSearch = MockTextSourceSearch()
    else:
        raise SourceSearchError(
            f"unknown source search provider '{settings.source_search_provider}'"
        )
    return CachedTextSourceSearch(inner, cache) if cache is not None else inner


__all__ = [
    "GENERIC_LIMITATIONS",
    "CachedImageSourceSearch",
    "CachedTextSourceSearch",
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
