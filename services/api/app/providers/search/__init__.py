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
from app.providers.search.google_vision import GoogleVisionImageSearch
from app.providers.search.mock import MockImageSourceSearch, MockTextSourceSearch
from app.providers.search.web import (
    OpenAlexBackend,
    SearxngBackend,
    TextBackend,
    WebTextSourceSearch,
    WikipediaBackend,
)


def build_image_source_search(
    settings: Settings, *, cache: ProviderResultCache | None = None
) -> ImageSourceSearch | None:
    if settings.source_search_provider == "none":
        return None
    inner: ImageSourceSearch
    if settings.source_search_provider == "mock":
        inner = MockImageSourceSearch()
    elif settings.source_search_provider == "web":
        if settings.source_search_image_backend != "google_vision":
            return None  # no real reverse-image backend chosen: the step is skipped
        key = settings.google_vision_api_key
        inner = GoogleVisionImageSearch(
            api_key=key.get_secret_value() if key else "",
            max_results=settings.google_vision_max_results,
            timeout_seconds=settings.source_search_timeout_seconds,
        )
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
    inner: TextSourceSearch
    if settings.source_search_provider == "mock":
        inner = MockTextSourceSearch()
    elif settings.source_search_provider == "web":
        backends: list[TextBackend] = []
        for name in settings.source_search_text_backends:
            if name == "wikipedia":
                backends.append(WikipediaBackend(settings.wikipedia_language))
            elif name == "openalex":
                backends.append(OpenAlexBackend())
            elif name == "searxng" and settings.searxng_base_url:
                backends.append(SearxngBackend(settings.searxng_base_url))
        if not backends:
            return None
        inner = WebTextSourceSearch(
            backends,
            results_per_phrase=settings.source_search_results_per_phrase,
            timeout_seconds=settings.source_search_timeout_seconds,
        )
    else:
        raise SourceSearchError(
            f"unknown source search provider '{settings.source_search_provider}'"
        )
    return CachedTextSourceSearch(inner, cache) if cache is not None else inner


__all__ = [
    "GENERIC_LIMITATIONS",
    "CachedImageSourceSearch",
    "CachedTextSourceSearch",
    "GoogleVisionImageSearch",
    "ImageSourceSearch",
    "MockImageSourceSearch",
    "MockTextSourceSearch",
    "OpenAlexBackend",
    "SearchResult",
    "SearxngBackend",
    "SourceKind",
    "SourceMatch",
    "SourceSearchError",
    "TextSourceSearch",
    "WebTextSourceSearch",
    "WikipediaBackend",
    "build_image_source_search",
    "build_text_source_search",
]
