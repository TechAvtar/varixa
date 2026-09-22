"""LLM synthesis adapters behind one interface. The model explains evidence; it never creates it."""

from datetime import timedelta

from app.config import Settings
from app.providers.cache import InMemoryProviderCache, ProviderResultCache
from app.providers.llm.base import (
    PROMPT_VERSION,
    SECTION_KEYS,
    SECTIONS,
    EvidenceForModel,
    LLMSynthesisError,
    LLMSynthesisUnavailableError,
    LLMSynthesizer,
    SectionDraft,
    SynthesisRequest,
    SynthesisResult,
    TimelineForModel,
    sections_from_json,
    sections_to_json,
)
from app.providers.llm.cache import CachedLLMSynthesizer
from app.providers.llm.mock import MOCK_MODEL, MockLLMSynthesizer
from app.providers.llm.openai import OpenAISynthesizer

_process_cache = InMemoryProviderCache(ttl=timedelta(hours=1))


def build_synthesizer(
    settings: Settings, *, cache: ProviderResultCache | None = None
) -> LLMSynthesizer | None:
    """The configured synthesiser wrapped in the result cache, or None when disabled."""
    provider = settings.llm_provider
    if provider == "none":
        return None
    inner: LLMSynthesizer
    if provider == "mock":
        inner = MockLLMSynthesizer()
        model_hint = MOCK_MODEL
    elif provider == "openai":
        key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
        inner = OpenAISynthesizer(
            api_key=key,
            model=settings.openai_model,
            base_url=settings.openai_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
            cost_per_million_in=settings.openai_cost_per_million_input,
            cost_per_million_out=settings.openai_cost_per_million_output,
        )
        model_hint = settings.openai_model
    else:  # pragma: no cover - guarded by the Settings Literal
        raise LLMSynthesisUnavailableError(f"unknown LLM provider '{provider}'")
    if settings.provider_cache_ttl_hours == 0:
        return CachedLLMSynthesizer(
            inner, InMemoryProviderCache(ttl=timedelta(0)), model_hint=model_hint
        )
    return CachedLLMSynthesizer(inner, cache or _process_cache, model_hint=model_hint)


__all__ = [
    "PROMPT_VERSION",
    "SECTIONS",
    "SECTION_KEYS",
    "CachedLLMSynthesizer",
    "EvidenceForModel",
    "LLMSynthesisError",
    "LLMSynthesisUnavailableError",
    "LLMSynthesizer",
    "MockLLMSynthesizer",
    "OpenAISynthesizer",
    "SectionDraft",
    "SynthesisRequest",
    "SynthesisResult",
    "TimelineForModel",
    "build_synthesizer",
    "sections_from_json",
    "sections_to_json",
]
