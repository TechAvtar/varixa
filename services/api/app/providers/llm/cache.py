"""Synthesis caching: the same evidence set through the same model is never re-billed."""

from dataclasses import replace
from typing import Any

from app.providers.cache import ProviderResultCache, cache_key
from app.providers.llm.base import (
    LLMSynthesizer,
    SynthesisRequest,
    SynthesisResult,
    sections_from_json,
    sections_to_json,
)


def serialize_synthesis(result: SynthesisResult) -> dict[str, Any]:
    return {
        "provider": result.provider,
        "model": result.model,
        "model_version": result.model_version,
        "sections": sections_to_json(result.sections),
        "raw": result.raw,
        "latency_ms": result.latency_ms,
        "request_id": result.request_id,
        "estimated_cost": result.estimated_cost,
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
    }


def deserialize_synthesis(payload: dict[str, Any]) -> SynthesisResult:
    return SynthesisResult(
        provider=str(payload["provider"]),
        model=str(payload["model"]),
        model_version=str(payload["model_version"]),
        sections=sections_from_json(payload.get("sections") or {}),
        raw=dict(payload.get("raw") or {}),
        latency_ms=payload.get("latency_ms"),
        request_id=payload.get("request_id"),
        cached=False,
        estimated_cost=payload.get("estimated_cost"),
        tokens_in=payload.get("tokens_in"),
        tokens_out=payload.get("tokens_out"),
    )


class CachedLLMSynthesizer:
    def __init__(
        self, inner: LLMSynthesizer, cache: ProviderResultCache, *, model_hint: str
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._model_hint = model_hint
        self.name = inner.name

    async def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        key = cache_key(
            provider=self.name,
            operation=f"llm.synthesize:{request.prompt_version}",
            model_version=self._model_hint,
            content_hash=request.fingerprint,
        )
        hit = await self._cache.get(key)
        if hit is not None:
            return replace(
                deserialize_synthesis(hit.payload), cached=True, latency_ms=0, estimated_cost=0.0
            )
        result = await self._inner.synthesize(request)
        await self._cache.set(
            key,
            serialize_synthesis(result),
            provider=self.name,
            operation=f"llm.synthesize:{request.prompt_version}",
            model_version=f"{result.model}@{result.model_version}",
            content_hash=request.fingerprint,
        )
        return result
