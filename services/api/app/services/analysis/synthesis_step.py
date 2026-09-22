"""LLM synthesis step: explain the stored evidence, verify the explanation, persist it.

Runs after the evidence step in both pipelines. Non-critical and skipped when no
provider is configured: the report then keeps the Interpretation section empty
rather than showing anything a model did not ground in evidence.
"""

from app.enums import ProviderCallStatus
from app.models import Synthesis
from app.providers.llm import (
    LLMSynthesisError,
    LLMSynthesizer,
    build_synthesizer,
)
from app.repositories.analysis import AnalysisRepository
from app.services.analysis.pipeline import PipelineContext, StepOutcome
from app.services.evidence.engine import EvidenceThresholds, synthesis_confidence
from app.services.provider_calls import ProviderCallRecorder
from app.services.synthesis.grounding import check_grounding
from app.services.synthesis.request import build_request
from app.services.usage import UsageService


class SynthesisStep:
    name = "synthesis"
    critical = False

    async def run(self, ctx: PipelineContext) -> StepOutcome:
        synthesizer: LLMSynthesizer | None
        if "synthesizer" in ctx.providers:
            synthesizer = ctx.providers["synthesizer"]
        else:
            synthesizer = build_synthesizer(ctx.settings)
        if synthesizer is None:
            return StepOutcome.skipped("no LLM synthesis provider configured")
        if await UsageService(ctx.session, ctx.settings).provider_budget_exhausted(
            ctx.analysis.user_id
        ):
            return StepOutcome.skipped("monthly provider budget reached; paid step skipped")

        repo = AnalysisRepository(ctx.session)
        aid = ctx.analysis.id
        evidence_rows = await repo.list_evidence(aid)
        if not evidence_rows:
            return StepOutcome.skipped("no evidence records to explain")
        timeline_rows = await repo.list_timeline(aid)
        thresholds = EvidenceThresholds.from_settings(ctx.settings)
        confidence = synthesis_confidence(
            [
                (r.level, float(r.confidence) if r.confidence is not None else None,
                 str((r.details or {}).get("kind") or "signal"))
                for r in evidence_rows
            ],
            thresholds,
        )  # fmt: skip
        prompt_version = ctx.settings.llm_prompt_version
        request = build_request(
            analysis_type=str(ctx.analysis.type),
            evidence_rows=evidence_rows,
            timeline_rows=timeline_rows,
            synthesis_confidence=confidence,
            prompt_version=prompt_version,
        )

        try:
            async with ProviderCallRecorder(ctx.session).track(
                analysis_id=aid,
                provider=synthesizer.name,
                operation="llm.synthesize",
                request_hash=request.fingerprint,
            ) as call:
                result = await synthesizer.synthesize(request)
                call.model_version = f"{result.model}@{result.model_version}"
                call.request_id = result.request_id
                call.estimated_cost = result.estimated_cost
                call.response = {
                    "tokens_in": result.tokens_in,
                    "tokens_out": result.tokens_out,
                    "sections": list(result.sections),
                }
                if result.cached:
                    call.status = ProviderCallStatus.CACHED
        except LLMSynthesisError as exc:
            return StepOutcome.failed("LLM_SYNTHESIS_FAILED", str(exc))
        except TimeoutError:
            return StepOutcome.failed("LLM_SYNTHESIS_TIMEOUT", "The synthesis provider timed out.")

        report = check_grounding(
            result.sections,
            evidence_ids={e.id for e in request.evidence},
            levels_present={e.level for e in request.evidence},
        )
        row = Synthesis(
            analysis_id=aid,
            provider=result.provider,
            model=result.model,
            model_version=result.model_version,
            prompt_version=prompt_version,
            evidence_fingerprint=request.fingerprint,
            sections_json={
                k: {
                    "text": s.text,
                    "evidence_ids": s.evidence_ids,
                    "dropped_ids": s.dropped_ids,
                    "grounded": s.grounded,
                }
                for k, s in report.sections.items()
            },
            grounded=report.grounded,
            warnings_json=report.warnings,
            cited_ids_json=report.cited_ids,
            cached=result.cached,
            latency_ms=result.latency_ms,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            estimated_cost=result.estimated_cost,
            raw_json=result.raw,
        )
        await repo.replace_synthesis(row)
        ctx.artifacts["synthesis"] = report
        return StepOutcome.ok(
            provider=result.provider,
            model=result.model,
            model_version=result.model_version,
            prompt_version=prompt_version,
            cached=result.cached,
            grounded=report.grounded,
            warnings=len(report.warnings),
            cited=len(report.cited_ids),
            records=len(request.evidence),
        )
