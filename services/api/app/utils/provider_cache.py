"""Pure helpers shared by every ``ProviderResultCache`` implementation: keys and the interface."""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


def cache_key(*, provider: str, operation: str, model_version: str, content_hash: str) -> str:
    raw = f"{provider}\x1f{operation}\x1f{model_version}\x1f{content_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def content_hash(content: bytes | str) -> str:
    data = content if isinstance(content, bytes) else content.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class CacheHit:
    payload: dict[str, Any]
    created_at: datetime
    hit_count: int


class ProviderResultCache(Protocol):
    async def get(self, key: str) -> CacheHit | None: ...

    async def set(
        self,
        key: str,
        payload: dict[str, Any],
        *,
        provider: str,
        operation: str,
        model_version: str,
        content_hash: str,
    ) -> None: ...
