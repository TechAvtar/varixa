"""Detection cache hooks. Keyed by content identity + provider/model/version.

Repeating the same content through the same model must not cost another
provider call. The MVP ships an in-process cache; T022 adds a persistent one
behind the same interface.
"""

import hashlib
from collections import OrderedDict
from dataclasses import replace
from typing import Any, Protocol

from app.providers.ai.base import AIDetector, DetectionResult, Modality


def detection_cache_key(
    content: bytes | str, *, provider: str, model: str, model_version: str, modality: str
) -> str:
    data = content if isinstance(content, bytes) else content.encode("utf-8")
    sha = hashlib.sha256(data).hexdigest()
    return f"ai:{provider}:{model}:{model_version}:{modality}:{sha}"


class DetectionCache(Protocol):
    async def get(self, key: str) -> DetectionResult | None: ...

    async def set(self, key: str, result: DetectionResult) -> None: ...


class InMemoryDetectionCache:
    """Bounded LRU. Per-process only; fine for a single worker."""

    def __init__(self, max_entries: int = 1024) -> None:
        self._max = max_entries
        self._items: OrderedDict[str, DetectionResult] = OrderedDict()

    async def get(self, key: str) -> DetectionResult | None:
        result = self._items.get(key)
        if result is not None:
            self._items.move_to_end(key)
        return result

    async def set(self, key: str, result: DetectionResult) -> None:
        self._items[key] = result
        self._items.move_to_end(key)
        while len(self._items) > self._max:
            self._items.popitem(last=False)


class CachedAIDetector:
    """Decorator: serves repeats from the cache and marks them ``cached=True``."""

    def __init__(self, inner: AIDetector, cache: DetectionCache, *, model_hint: str) -> None:
        self._inner = inner
        self._cache = cache
        self.name = inner.name
        self.modalities = inner.modalities
        # Cache keys must include the model identity before the call is made.
        self._model_hint = model_hint

    async def detect(
        self, content: bytes | str, *, modality: Modality, metadata: dict[str, Any]
    ) -> DetectionResult:
        key = detection_cache_key(
            content,
            provider=self.name,
            model=self._model_hint,
            model_version="*",
            modality=modality,
        )
        hit = await self._cache.get(key)
        if hit is not None:
            return replace(hit, cached=True, latency_ms=0)
        result = await self._inner.detect(content, modality=modality, metadata=metadata)
        await self._cache.set(key, result)
        return result
