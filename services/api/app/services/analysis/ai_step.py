"""AI-generation signal step, shared by the image and text pipelines.

Non-critical: a missing or failing detector must never sink deterministic
evidence. When no provider is configured the step is *skipped* and nothing is
persisted, so the report keeps saying UNKNOWN rather than inventing a result.
"""

from typing import Any

from app.enums import AnalysisType, ProviderCallStatus
from app.models import AIDetection
from app.providers.ai import (
    AIDetector,
    AIDetectorError,
    Modality,
    build_ai_detector,
)
from app.repositories.analysis import AnalysisRepository
from app.services.analysis.pipeline import PipelineContext, StepFailedError, StepOutcome
from app.services.provider_calls import ProviderCallRecorder, request_hash
from app.services.usage import UsageService


class AIDetectionStep:
    name = "ai"
    critical = False

    async def run(self, ctx: PipelineContext) -> StepOutcome:
        detector: AIDetector | None
        if "ai_detector" in ctx.providers:
            detector = ctx.providers["ai_detector"]
        else:
            detector = build_ai_detector(ctx.settings)
        if detector is None:
            return StepOutcome.skipped("no AI detector configured")
        if await UsageService(ctx.session, ctx.settings).provider_budget_exhausted(
            ctx.analysis.user_id
        ):
            return StepOutcome.skipped("monthly provider budget reached; paid step skipped")

        modality: Modality
        content: bytes | str
        metadata: dict[str, Any]
        if ctx.analysis.type == AnalysisType.IMAGE:
            image = ctx.artifacts.get("image")
            if image is None:
                raise StepFailedError("NO_VERIFIED_IMAGE", "Validation did not publish an image.")
            modality, content = "image", image.data
            metadata = {"mime_type": image.mime_type, "width": image.width, "height": image.height}
        else:
            text = ctx.artifacts.get("text")
            if text is None:
                raise StepFailedError("NO_NORMALIZED_TEXT", "Normalisation did not run.")
            modality, content = "text", text.normalized
            metadata = {"chars": len(text.normalized)}
        if modality not in detector.modalities:
            return StepOutcome.skipped(f"provider {detector.name} does not support {modality}")

        recorder = ProviderCallRecorder(ctx.session)
        try:
            async with recorder.track(
                analysis_id=ctx.analysis.id,
                provider=detector.name,
                operation="ai.detect",
                request_hash=request_hash(content),
            ) as call:
                result = await detector.detect(content, modality=modality, metadata=metadata)
                call.model_version = f"{result.model}@{result.model_version}"
                call.request_id = result.request_id
                call.estimated_cost = result.estimated_cost
                call.status = ProviderCallStatus.CACHED if result.cached else call.status
                call.response = {
                    "score": result.score,
                    "label": result.label,
                    "calibrated": result.calibrated,
                    "cached": result.cached,
                    "raw": result.raw,
                }
        except AIDetectorError as exc:
            raise StepFailedError("AI_PROVIDER_FAILED", str(exc)[:300]) from exc

        row = AIDetection(
            analysis_id=ctx.analysis.id,
            modality=modality,
            provider=result.provider,
            model=result.model,
            provider_version=result.model_version,
            score=result.score,
            label=result.label,
            calibrated=result.calibrated,
            cached=result.cached,
            latency_ms=result.latency_ms,
            request_id=result.request_id,
            threshold_high=ctx.settings.ai_score_high,
            threshold_medium=ctx.settings.ai_score_medium,
            limitations_json=list(result.limitations),
            raw_json=dict(result.raw),
        )
        await AnalysisRepository(ctx.session).replace_ai_detection(row)
        ctx.artifacts["ai_detection"] = result
        return StepOutcome.ok(
            provider=result.provider,
            model=result.model,
            model_version=result.model_version,
            score=result.score,
            label=result.label,
            calibrated=result.calibrated,
            cached=result.cached,
            latency_ms=result.latency_ms,
        )
