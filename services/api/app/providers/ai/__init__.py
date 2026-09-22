"""AI-generation detector adapters behind one interface. Output is always a signal, never proof."""

from datetime import timedelta

from app.config import Settings
from app.providers.ai.base import (
    GENERIC_LIMITATIONS,
    AIDetector,
    AIDetectorError,
    AIDetectorUnavailableError,
    DetectionResult,
    Label,
    Modality,
    label_for_score,
)
from app.providers.ai.cache import CachedAIDetector, deserialize_detection, serialize_detection
from app.providers.ai.mock import MOCK_MODEL, MockAIDetector
from app.providers.cache import InMemoryProviderCache, ProviderResultCache

_process_cache = InMemoryProviderCache(ttl=timedelta(hours=1))


def build_ai_detector(
    settings: Settings, *, cache: ProviderResultCache | None = None
) -> AIDetector | None:
    """Return the configured detector (wrapped in the cache) or None when disabled.

    Real vendor adapters plug in here by name; each must live in ``providers/ai/``
    and translate its API into ``DetectionResult`` without leaking vendor fields.
    """
    provider = settings.ai_detector_provider
    if provider == "none":
        return None
    if provider == "mock":
        inner: AIDetector = MockAIDetector(
            high=settings.ai_score_high, medium=settings.ai_score_medium
        )
        model_hint = MOCK_MODEL
    else:  # pragma: no cover - guarded by the Settings Literal
        raise AIDetectorUnavailableError(f"unknown AI detector provider '{provider}'")
    if settings.provider_cache_ttl_hours == 0:
        return CachedAIDetector(
            inner, InMemoryProviderCache(ttl=timedelta(0)), model_hint=model_hint
        )
    return CachedAIDetector(inner, cache or _process_cache, model_hint=model_hint)


__all__ = [
    "GENERIC_LIMITATIONS",
    "AIDetector",
    "AIDetectorError",
    "AIDetectorUnavailableError",
    "CachedAIDetector",
    "DetectionResult",
    "Label",
    "MockAIDetector",
    "Modality",
    "build_ai_detector",
    "deserialize_detection",
    "label_for_score",
    "serialize_detection",
]
