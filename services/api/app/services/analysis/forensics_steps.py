"""Forensic pipeline steps. Each method is a heuristic and says so in its own record.

Every step writes into the single ``image_forensics`` row for the analysis (its
own column only) so later methods (T024-T027) compose without clobbering each
other. Visualisations are stored as private artifacts under the owner's prefix.
"""

import asyncio
import io
from typing import Any

from PIL import Image

from app.repositories.analysis import AnalysisRepository
from app.services import storage_keys
from app.services.analysis.pipeline import PipelineContext, StepFailedError, StepOutcome
from app.services.image import compression, copy_move, ela, noise, resampling
from app.services.usage import UsageService

ELA_ARTIFACT = "ela.png"
NOISE_ARTIFACT = "noise.png"
COPY_MOVE_ARTIFACT = "copy_move.png"


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


class ResamplingStep:
    """Global resampling (rescale/rotate) trace via prediction-residual spectrum. Non-critical.

    Writes ``resampling_json`` only. Produces no artifact.
    """

    name = "resampling"
    critical = False

    async def run(self, ctx: PipelineContext) -> StepOutcome:
        image = ctx.artifacts.get("image")
        if image is None:
            raise StepFailedError("NO_VERIFIED_IMAGE", "Validation did not publish an image.")
        result = await asyncio.to_thread(
            resampling.analyze_resampling,
            image.data,
            min_peak_ratio=ctx.settings.resampling_min_peak_ratio,
        )
        await AnalysisRepository(ctx.session).upsert_forensics(
            ctx.analysis.id, resampling_json=result.to_json()
        )
        ctx.artifacts["resampling"] = result
        return StepOutcome.ok(
            version=resampling.RESAMPLING_VERSION,
            measured=result.measured,
            tiles=result.tiles,
            peak_ratio=result.peak_ratio,
            peaks=len(result.peaks),
            detected=result.detected,
        )


class NoiseStep:
    """Block-wise noise-level consistency over smooth areas (any format). Non-critical.

    Persists ``noise_json`` and a block-level noise map as ``noise.png``.
    """

    name = "noise"
    critical = False

    async def run(self, ctx: PipelineContext) -> StepOutcome:
        image = ctx.artifacts.get("image")
        if image is None:
            raise StepFailedError("NO_VERIFIED_IMAGE", "Validation did not publish an image.")
        s = ctx.settings
        result = await asyncio.to_thread(
            noise.analyze_noise,
            image.data,
            block_size=s.noise_block_size,
            outlier_k=s.noise_outlier_k,
            anomaly_min_fraction=s.noise_anomaly_min_fraction,
            anomaly_max_fraction=s.noise_anomaly_max_fraction,
        )
        repo = AnalysisRepository(ctx.session)
        row = await repo.upsert_forensics(ctx.analysis.id, noise_json=result.to_json())
        if result.visualization_png:
            key = storage_keys.artifact_key(ctx.analysis.user_id, ctx.analysis.id, NOISE_ARTIFACT)
            await ctx.storage.put(key, result.visualization_png, content_type="image/png")
            await UsageService(ctx.session, ctx.settings).record_storage(
                ctx.analysis.user_id, len(result.visualization_png)
            )
            with Image.open(io.BytesIO(result.visualization_png)) as vis:
                vw, vh = vis.size
            others = [a for a in (row.artifacts_json or []) if a.get("method") != noise.METHOD]
            row.artifacts_json = [
                *others,
                {
                    "name": NOISE_ARTIFACT,
                    "method": noise.METHOD,
                    "object_key": key,
                    "content_type": "image/png",
                    "width": vw,
                    "height": vh,
                    "size_bytes": len(result.visualization_png),
                },
            ]
            await ctx.session.flush()
        ctx.artifacts["noise"] = result
        return StepOutcome.ok(
            version=noise.NOISE_VERSION,
            measured=result.measured,
            baseline_sigma=result.baseline_sigma,
            blocks_smooth=result.blocks_smooth,
            outlier_fraction=result.outlier_fraction,
            regions=len(result.regions),
            anomaly=result.anomaly,
            artifact=NOISE_ARTIFACT if result.visualization_png else None,
        )


def _record_artifact(row: Any, *, name: str, method: str, key: str, png: bytes) -> None:
    """Replace this method's entry in the row's artifact list (never exposed as a raw key)."""
    with Image.open(io.BytesIO(png)) as vis:
        vw, vh = vis.size
    others = [a for a in (row.artifacts_json or []) if a.get("method") != method]
    row.artifacts_json = [
        *others,
        {
            "name": name,
            "method": method,
            "object_key": key,
            "content_type": "image/png",
            "width": vw,
            "height": vh,
            "size_bytes": len(png),
        },
    ]


class CopyMoveStep:
    """Translated-duplicate (cloning) detection by block matching. Non-critical.

    Persists ``copy_move_json`` and a mask of matched source (grey) and target
    (white) blocks as ``copy_move.png`` at the working size.
    """

    name = "copy_move"
    critical = False

    async def run(self, ctx: PipelineContext) -> StepOutcome:
        image = ctx.artifacts.get("image")
        if image is None:
            raise StepFailedError("NO_VERIFIED_IMAGE", "Validation did not publish an image.")
        s = ctx.settings
        result = await asyncio.to_thread(
            copy_move.analyze_copy_move,
            image.data,
            max_side=s.copy_move_max_side,
            min_matches=s.copy_move_min_matches,
            min_shift=s.copy_move_min_shift,
        )
        repo = AnalysisRepository(ctx.session)
        row = await repo.upsert_forensics(ctx.analysis.id, copy_move_json=result.to_json())
        if result.visualization_png:
            key = storage_keys.artifact_key(
                ctx.analysis.user_id, ctx.analysis.id, COPY_MOVE_ARTIFACT
            )
            await ctx.storage.put(key, result.visualization_png, content_type="image/png")
            await UsageService(ctx.session, ctx.settings).record_storage(
                ctx.analysis.user_id, len(result.visualization_png)
            )
            _record_artifact(
                row,
                name=COPY_MOVE_ARTIFACT,
                method=copy_move.METHOD,
                key=key,
                png=result.visualization_png,
            )
            await ctx.session.flush()
        ctx.artifacts["copy_move"] = result
        return StepOutcome.ok(
            version=copy_move.COPY_MOVE_VERSION,
            measured=result.measured,
            downscaled=result.downscaled,
            blocks_textured=result.blocks_textured,
            candidate_pairs=result.candidate_pairs,
            matches=len(result.matches),
            detected=result.detected,
            artifact=COPY_MOVE_ARTIFACT if result.visualization_png else None,
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
        await UsageService(ctx.session, ctx.settings).record_storage(
            ctx.analysis.user_id, len(result.visualization_png)
        )
        artifact = {
            "name": ELA_ARTIFACT,
            "method": ela.METHOD,
            "object_key": key,
            "content_type": "image/png",
            "width": result.working_width,
            "height": result.working_height,
            "size_bytes": len(result.visualization_png),
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
