"""Detection caching: repeats of the same content through the same model cost nothing.

``CachedAIDetector`` wraps any detector with a ``ProviderResultCache`` (the
persistent DB cache in production, in-memory in tests). Results are stored as
plain JSON and rebuilt into ``DetectionResult`` on a hit.
"""

from dataclasses import asdict, replace
from typing import Any

from app.providers.ai.base import AIDetector, DetectionResult, Modality
from app.providers.cache import ProviderResultCache, cache_key, content_hash

OPERATION = "ai.detect"


def serialize_detection(result: DetectionResult) -> dict[str, Any]:
    data = asdict(result)
    data.pop("cached", None)
    return data


def deserialize_detection(payload: dict[str, Any]) -> DetectionResult:
    return DetectionResult(
        provider=str(payload["provider"]),
        model=str(payload["model"]),
        model_version=str(payload["model_version"]),
        modality=payload["modality"],
        score=payload.get("score"),
        label=payload.get("label", "unavailable"),
        calibrated=bool(payload.get("calibrated", False)),
        raw=dict(payload.get("raw") or {}),
        latency_ms=payload.get("latency_ms"),
        request_id=payload.get("request_id"),
        cached=False,
        estimated_cost=payload.get("estimated_cost"),
        limitations=list(payload.get("limitations") or []),
    )


class CachedAIDetector:
    """Decorator: serves repeats from the cache and marks them ``cached=True`` at zero cost."""

    def __init__(self, inner: AIDetector, cache: ProviderResultCache, *, model_hint: str) -> None:
        self._inner = inner
        self._cache = cache
        self.name = inner.name
        self.modalities = inner.modalities
        # The model identity must be part of the key before the call is made.
        self._model_hint = model_hint

    async def detect(
        self, content: bytes | str, *, modality: Modality, metadata: dict[str, Any]
    ) -> DetectionResult:
        chash = content_hash(content)
        key = cache_key(
            provider=self.name,
            operation=f"{OPERATION}:{modality}",
            model_version=self._model_hint,
            content_hash=chash,
        )
        hit = await self._cache.get(key)
        if hit is not None:
            return replace(
                deserialize_detection(hit.payload), cached=True, latency_ms=0, estimated_cost=0.0
            )
        result = await self._inner.detect(content, modality=modality, metadata=metadata)
        await self._cache.set(
            key,
            serialize_detection(result),
            provider=self.name,
            operation=f"{OPERATION}:{modality}",
            model_version=f"{result.model}@{result.model_version}",
            content_hash=chash,
        )
        return result
