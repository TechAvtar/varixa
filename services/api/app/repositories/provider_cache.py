"""Database-backed ``ProviderResultCache`` over the ``provider_cache`` table."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provider_cache import ProviderCacheEntry
from app.utils.provider_cache import CacheHit


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class DbProviderCache:
    """Database-backed cache. Expired rows are ignored on read and pruned on write."""

    def __init__(self, session: AsyncSession, *, ttl: timedelta) -> None:
        self._session = session
        self._ttl = ttl

    async def get(self, key: str) -> CacheHit | None:
        row = (
            await self._session.execute(
                select(ProviderCacheEntry).where(ProviderCacheEntry.cache_key == key)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        now = datetime.now(UTC)
        if _as_utc(row.expires_at) <= now:
            return None
        row.hit_count += 1
        row.last_hit_at = now
        await self._session.flush()
        return CacheHit(
            payload=row.payload_json, created_at=row.created_at, hit_count=row.hit_count
        )

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
        now = datetime.now(UTC)
        await self._session.execute(
            delete(ProviderCacheEntry).where(ProviderCacheEntry.cache_key == key)
        )
        self._session.add(
            ProviderCacheEntry(
                cache_key=key,
                provider=provider[:64],
                operation=operation[:64],
                model_version=model_version[:128],
                content_hash=content_hash,
                payload_json=payload,
                expires_at=now + self._ttl,
            )
        )
        await self._session.flush()

    async def purge_expired(self) -> int:
        result = await self._session.execute(
            delete(ProviderCacheEntry).where(ProviderCacheEntry.expires_at <= datetime.now(UTC))
        )
        return int(getattr(result, "rowcount", 0) or 0)
