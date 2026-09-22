"""Search-result caching: identical content/phrases through the same provider are not re-queried.

Search indexes change over time, so entries carry the cache TTL like every other
provider result; ``discovered_at`` in cached matches is the original discovery time.
"""

from dataclasses import asdict, replace
from datetime import datetime
from typing import Any

from app.providers.cache import ProviderResultCache, cache_key, content_hash
from app.providers.search.base import (
    ImageSourceSearch,
    SearchResult,
    SourceMatch,
    TextSourceSearch,
)


def serialize_search(result: SearchResult) -> dict[str, Any]:
    data = asdict(result)
    data.pop("cached", None)
    for m in data["matches"]:
        m["discovered_at"] = m["discovered_at"].isoformat()
    return data


def deserialize_search(payload: dict[str, Any]) -> SearchResult:
    matches = [
        SourceMatch(
            provider=str(m["provider"]),
            url=str(m["url"]),
            title=m.get("title"),
            snippet=m.get("snippet"),
            similarity=m.get("similarity"),
            source_kind=m.get("source_kind", "unknown"),
            matched_phrase=m.get("matched_phrase"),
            published_at=m.get("published_at"),
            discovered_at=datetime.fromisoformat(str(m["discovered_at"])),
            raw=dict(m.get("raw") or {}),
        )
        for m in payload.get("matches") or []
    ]
    return SearchResult(
        provider=str(payload["provider"]),
        provider_version=str(payload["provider_version"]),
        modality=payload["modality"],
        matches=matches,
        queried_phrases=list(payload.get("queried_phrases") or []),
        latency_ms=payload.get("latency_ms"),
        request_id=payload.get("request_id"),
        cached=False,
        estimated_cost=payload.get("estimated_cost"),
        limitations=list(payload.get("limitations") or []),
    )


class CachedImageSourceSearch:
    def __init__(self, inner: ImageSourceSearch, cache: ProviderResultCache) -> None:
        self._inner = inner
        self._cache = cache
        self.name = inner.name

    async def search_image(self, content: bytes, *, metadata: dict[str, Any]) -> SearchResult:
        chash = content_hash(content)
        key = cache_key(
            provider=self.name, operation="search.image", model_version="*", content_hash=chash
        )
        hit = await self._cache.get(key)
        if hit is not None:
            return replace(
                deserialize_search(hit.payload), cached=True, latency_ms=0, estimated_cost=0.0
            )
        result = await self._inner.search_image(content, metadata=metadata)
        await self._cache.set(
            key,
            serialize_search(result),
            provider=self.name,
            operation="search.image",
            model_version=result.provider_version,
            content_hash=chash,
        )
        return result


class CachedTextSourceSearch:
    def __init__(self, inner: TextSourceSearch, cache: ProviderResultCache) -> None:
        self._inner = inner
        self._cache = cache
        self.name = inner.name

    async def search_text(self, text: str, *, phrases: list[str]) -> SearchResult:
        # The queried phrases fully determine the request, so they form the content identity.
        chash = content_hash("\n".join(phrases))
        key = cache_key(
            provider=self.name, operation="search.text", model_version="*", content_hash=chash
        )
        hit = await self._cache.get(key)
        if hit is not None:
            return replace(
                deserialize_search(hit.payload), cached=True, latency_ms=0, estimated_cost=0.0
            )
        result = await self._inner.search_text(text, phrases=phrases)
        await self._cache.set(
            key,
            serialize_search(result),
            provider=self.name,
            operation="search.text",
            model_version=result.provider_version,
            content_hash=chash,
        )
        return result
