"""Cache wrappers for repeatable provider results.

Keyed by ``sha256(provider | operation | model_version | content_hash)``. Only
*safe, repeatable* operations belong here: the same content sent to the same
model/version yields the same answer, so a second paid call is waste.

Interface and key helpers live in ``app.utils.provider_cache``; the database-backed
implementation lives in ``app.repositories.provider_cache`` (providers never touch models).
This module re-exports the interface and provides the in-memory implementation.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.utils.provider_cache import CacheHit, ProviderResultCache, cache_key, content_hash

__all__ = [
    "CacheHit",
    "InMemoryProviderCache",
    "ProviderResultCache",
    "cache_key",
    "content_hash",
]


class InMemoryProviderCache:
    """Process-local cache for tests and single-process dev; honours TTL."""

    def __init__(self, *, ttl: timedelta) -> None:
        self._ttl = ttl
        self._items: dict[str, tuple[dict[str, Any], datetime, int]] = {}

    async def get(self, key: str) -> CacheHit | None:
        item = self._items.get(key)
        if item is None:
            return None
        payload, created, hits = item
        if created + self._ttl <= datetime.now(UTC):
            del self._items[key]
            return None
        self._items[key] = (payload, created, hits + 1)
        return CacheHit(payload=payload, created_at=created, hit_count=hits + 1)

    async def set(
        self,
        key: str,
        payload: dict[str, Any],
        *,
        provider: str,
        operation: str,
        model_version: str,
        content_hash: str,
    ) -> None:
        self._items[key] = (payload, datetime.now(UTC), 0)
