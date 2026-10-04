"""AI-generation detector adapters behind one interface. Output is always a signal, never proof."""

import asyncio
import logging
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
from app.providers.ai.local import LocalAIDetector, TransformersRuntime
from app.providers.ai.mock import MOCK_MODEL, MockAIDetector
from app.providers.cache import InMemoryProviderCache, ProviderResultCache

log = logging.getLogger("verixa.ai")
_process_cache = InMemoryProviderCache(ttl=timedelta(hours=1))


_local_runtimes: dict[tuple[object, ...], TransformersRuntime] = {}


def _local_runtime(settings: Settings) -> TransformersRuntime:
    """One runtime per configuration for the whole process: loading a model is slow and big,
    and the pipeline builds its providers once per analysis."""
    key: tuple[object, ...] = (
        settings.detector_model_dir,
        settings.ai_detector_image_model,
        settings.ai_detector_image_ai_label,
        settings.ai_detector_text_model,
        settings.ai_detector_text_ai_label,
        settings.ai_detector_text_min_tokens,
        settings.ai_detector_text_max_chunks,
    )
    runtime = _local_runtimes.get(key)
    if runtime is None:
        runtime = _local_runtimes[key] = TransformersRuntime(
            model_dir=settings.detector_model_dir,
            image_model=settings.ai_detector_image_model,
            image_ai_label=settings.ai_detector_image_ai_label,
            text_model=settings.ai_detector_text_model,
            text_ai_label=settings.ai_detector_text_ai_label,
            text_min_tokens=settings.ai_detector_text_min_tokens,
            text_max_chunks=settings.ai_detector_text_max_chunks,
        )
    return runtime


async def warm_ai_detector(settings: Settings) -> None:
    """Load the local models in the background at startup so the first analysis is not slow.

    Never raises: a missing model or library is reported in the log and again, with the same
    message, by the first analysis that needs it.
    """
    if settings.ai_detector_provider != "local":
        return
    runtime = _local_runtime(settings)
    for modality in ("image", "text"):
        try:
            await asyncio.to_thread(runtime.prepare, modality)
            log.info("local AI detector ready", extra={"modality": modality})
        except Exception as exc:
            log.warning(
                "local AI detector not ready",
                extra={"modality": modality, "reason": str(exc)[:200]},
            )


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
    elif provider == "local":
        local = LocalAIDetector(
            _local_runtime(settings),
            image_ai_label=settings.ai_detector_image_ai_label,
            text_ai_label=settings.ai_detector_text_ai_label,
            high=settings.ai_score_high,
            medium=settings.ai_score_medium,
            timeout_seconds=settings.ai_detector_timeout_seconds,
            load_timeout_seconds=settings.ai_detector_load_timeout_seconds,
        )
        inner = local
        model_hint = local.model_hint()
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
    "LocalAIDetector",
    "MockAIDetector",
    "Modality",
    "build_ai_detector",
    "deserialize_detection",
    "label_for_score",
    "serialize_detection",
    "warm_ai_detector",
]
