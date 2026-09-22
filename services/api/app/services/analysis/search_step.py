"""Source / reverse-search step shared by the image and text pipelines.

Non-critical and skipped when no provider is configured, so absence of a
search is reported as UNKNOWN rather than as "no sources found".
"""

from typing import Any

from app.enums import AnalysisType, ProviderCallStatus
from app.models import SourceMatch, SourceSearchRun
from app.providers.search import (
    ImageSourceSearch,
    SearchResult,
    SourceSearchError,
    TextSourceSearch,
    build_image_source_search,
    build_text_source_search,
)
from app.repositories.analysis import AnalysisRepository
from app.services.analysis.pipeline import PipelineContext, StepFailedError, StepOutcome
from app.services.provider_calls import ProviderCallRecorder, request_hash
from app.services.text.phrases import select_distinctive_phrases

MAX_MATCHES = 50


class SourceSearchStep:
    name = "search"
    critical = False

    async def run(self, ctx: PipelineContext) -> StepOutcome:
        if ctx.analysis.type == AnalysisType.IMAGE:
            result = await self._search_image(ctx)
        else:
            result = await self._search_text(ctx)
        if result is None:
            return StepOutcome.skipped("no source search provider configured")

        repo = AnalysisRepository(ctx.session)
        matches = [
            SourceMatch(
                analysis_id=ctx.analysis.id,
                provider=m.provider,
                provider_version=result.provider_version,
                rank=i + 1,
                url=m.url[:2048],
                title=(m.title or None) and m.title[:500],
                snippet=(m.snippet or None) and m.snippet[:1000],
                similarity=m.similarity,
                source_kind=m.source_kind,
                matched_phrase=(m.matched_phrase or None) and m.matched_phrase[:500],
                published_at=m.published_at,
                discovered_at=m.discovered_at,
                raw_json=dict(m.raw),
            )
            for i, m in enumerate(result.matches[:MAX_MATCHES])
        ]
        run = SourceSearchRun(
            analysis_id=ctx.analysis.id,
            modality=result.modality,
            provider=result.provider,
            provider_version=result.provider_version,
            queried_phrases_json=list(result.queried_phrases),
            match_count=len(matches),
            latency_ms=result.latency_ms,
            request_id=result.request_id,
            limitations_json=list(result.limitations),
        )
        await repo.replace_source_search(run, matches)
        ctx.artifacts["source_search"] = result
        return StepOutcome.ok(
            provider=result.provider,
            provider_version=result.provider_version,
            match_count=len(matches),
            queried_phrases=len(result.queried_phrases),
            latency_ms=result.latency_ms,
            cached=result.cached,
        )

    async def _search_image(self, ctx: PipelineContext) -> SearchResult | None:
        provider: ImageSourceSearch | None = (
            ctx.providers["image_search"]
            if "image_search" in ctx.providers
            else build_image_source_search(ctx.settings)
        )
        if provider is None:
            return None
        image = ctx.artifacts.get("image")
        if image is None:
            raise StepFailedError("NO_VERIFIED_IMAGE", "Validation did not publish an image.")
        metadata: dict[str, Any] = {"mime_type": image.mime_type, "sha256": image.sha256}
        try:
            async with ProviderCallRecorder(ctx.session).track(
                analysis_id=ctx.analysis.id,
                provider=provider.name,
                operation="search.image",
                request_hash=image.sha256,
            ) as call:
                result = await provider.search_image(image.data, metadata=metadata)
                _fill_call(call, result)
                return result
        except SourceSearchError as exc:
            raise StepFailedError("SEARCH_PROVIDER_FAILED", str(exc)[:300]) from exc

    async def _search_text(self, ctx: PipelineContext) -> SearchResult | None:
        provider: TextSourceSearch | None = (
            ctx.providers["text_search"]
            if "text_search" in ctx.providers
            else build_text_source_search(ctx.settings)
        )
        if provider is None:
            return None
        text = ctx.artifacts.get("text")
        if text is None:
            raise StepFailedError("NO_NORMALIZED_TEXT", "Normalisation did not run.")
        phrases = select_distinctive_phrases(
            text.normalized, max_phrases=ctx.settings.text_search_max_phrases
        )
        if not phrases:
            return SearchResult(
                provider=provider.name,
                provider_version="n/a",
                modality="text",
                matches=[],
                queried_phrases=[],
                limitations=["The text was too short to extract a distinctive phrase to search."],
            )
        try:
            async with ProviderCallRecorder(ctx.session).track(
                analysis_id=ctx.analysis.id,
                provider=provider.name,
                operation="search.text",
                request_hash=request_hash("\n".join(phrases)),
            ) as call:
                result = await provider.search_text(text.normalized, phrases=phrases)
                _fill_call(call, result)
                return result
        except SourceSearchError as exc:
            raise StepFailedError("SEARCH_PROVIDER_FAILED", str(exc)[:300]) from exc


def _fill_call(call: Any, result: SearchResult) -> None:
    call.model_version = result.provider_version
    call.request_id = result.request_id
    call.estimated_cost = result.estimated_cost
    if result.cached:
        call.status = ProviderCallStatus.CACHED
    call.response = {
        "match_count": len(result.matches),
        "queried_phrases": len(result.queried_phrases),
        "cached": result.cached,
    }
