"""Forensic pipeline steps. Each method is a heuristic and says so in its own record.

Every step writes into the single ``image_forensics`` row for the analysis (its
own column only) so later methods (T024-T027) compose without clobbering each
other. Visualisations are stored as private artifacts under the owner's prefix.
"""

import asyncio

from app.repositories.analysis import AnalysisRepository
from app.services import storage_keys
from app.services.analysis.pipeline import PipelineContext, StepFailedError, StepOutcome
from app.services.image import compression, ela

ELA_ARTIFACT = "ela.png"


class CompressionStep:
    """JPEG encoding facts plus the 8x8 block-grid heuristic (any format). Non-critical.

    Writes ``compression_json`` only. Produces no artifact.
    """

    name = "compression"
    critical = False

    async def run(self, ctx: PipelineContext) -> StepOutcome:
        image = ctx.artifacts.get("image")
        if image is None:
            raise StepFailedError("NO_VERIFIED_IMAGE", "Validation did not publish an image.")
        result = await asyncio.to_thread(
            compression.analyze_compression,
            image.data,
            grid_min_strength=ctx.settings.compression_grid_min_strength,
        )
        await AnalysisRepository(ctx.session).upsert_forensics(
            ctx.analysis.id, compression_json=result.to_json()
        )
        ctx.artifacts["compression"] = result
        enc = result.encoding
        return StepOutcome.ok(
            version=compression.COMPRESSION_VERSION,
            format=result.format,
            estimated_quality=enc.estimated_quality if enc else None,
            standard_tables=enc.standard_tables if enc else None,
            subsampling=enc.subsampling if enc else None,
            progressive=enc.progressive if enc else None,
            grid_measured=result.grid.measured,
            grid_aligned=result.grid.detected_aligned,
            grid_offset=result.grid.detected_offset,
            anomaly=result.anomaly,
            prior_jpeg_grid=result.prior_jpeg_grid,
        )


class ELAStep:
    """Error Level Analysis for JPEG sources. Non-critical; other formats are recorded as skipped.

    Persists the structured observation (``ela_json``) and an amplified
    difference map as ``artifacts/<user>/<analysis>/ela.png``.
    """

    name = "ela"
    critical = False

    async def run(self, ctx: PipelineContext) -> StepOutcome:
        image = ctx.artifacts.get("image")
        if image is None:
            raise StepFailedError("NO_VERIFIED_IMAGE", "Validation did not publish an image.")
        repo = AnalysisRepository(ctx.session)

        if image.pil_format not in ela.APPLICABLE_FORMATS:
            await repo.upsert_forensics(
                ctx.analysis.id, ela_json=ela.not_applicable_json(image.pil_format)
            )
            return StepOutcome.skipped(ela.NOT_APPLICABLE_REASON, format=image.pil_format)

        s = ctx.settings
        result = await asyncio.to_thread(
            ela.compute_ela,
            image.data,
            quality=s.ela_quality,
            max_side=s.ela_max_side,
            outlier_sigma=s.ela_outlier_sigma,
            anomaly_min_fraction=s.ela_anomaly_min_fraction,
            anomaly_max_fraction=s.ela_anomaly_max_fraction,
        )

        key = storage_keys.artifact_key(ctx.analysis.user_id, ctx.analysis.id, ELA_ARTIFACT)
        await ctx.storage.put(key, result.visualization_png, content_type="image/png")
        artifact = {
            "name": ELA_ARTIFACT,
            "method": ela.METHOD,
            "object_key": key,
            "content_type": "image/png",
            "width": result.working_width,
            "height": result.working_height,
        }
        row = await repo.upsert_forensics(ctx.analysis.id, ela_json=result.to_json())
        others = [a for a in (row.artifacts_json or []) if a.get("method") != ela.METHOD]
        row.artifacts_json = [*others, artifact]
        await ctx.session.flush()
        ctx.artifacts["ela"] = result

        return StepOutcome.ok(
            version=ela.ELA_VERSION,
            quality=result.quality,
            downscaled=result.downscaled,
            mean_error=result.mean_error,
            outlier_block_fraction=result.outlier_block_fraction,
            regions=len(result.regions),
            anomaly=result.anomaly,
            artifact=ELA_ARTIFACT,
        )
