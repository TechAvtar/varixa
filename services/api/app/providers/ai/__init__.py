"""AI-generation detector adapters behind one interface. Output is always a signal, never proof."""

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
from app.providers.ai.cache import (
    CachedAIDetector,
    DetectionCache,
    InMemoryDetectionCache,
    detection_cache_key,
)
from app.providers.ai.mock import MOCK_MODEL, MockAIDetector

_process_cache = InMemoryDetectionCache()


def build_ai_detector(
    settings: Settings, *, cache: DetectionCache | None = None
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
    return CachedAIDetector(inner, cache or _process_cache, model_hint=model_hint)


__all__ = [
    "GENERIC_LIMITATIONS",
    "AIDetector",
    "AIDetectorError",
    "AIDetectorUnavailableError",
    "CachedAIDetector",
    "DetectionCache",
    "DetectionResult",
    "InMemoryDetectionCache",
    "Label",
    "MockAIDetector",
    "Modality",
    "build_ai_detector",
    "detection_cache_key",
    "label_for_score",
]
