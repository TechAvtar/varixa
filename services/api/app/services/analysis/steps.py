"""Concrete pipeline steps for image analyses. Each is small and independently testable."""

from app.models import ImageMetadata
from app.providers.metadata import (
    MetadataExtractionError,
    MetadataExtractor,
    build_metadata_extractor,
)
from app.providers.storage.base import ObjectNotFoundError
from app.repositories.analysis import AnalysisRepository
from app.services.analysis.pipeline import PipelineContext, StepFailedError, StepOutcome
from app.services.image import validate_image
from app.services.image.hashing import compute_hashes
from app.services.image.metadata import normalize_metadata, to_utc_or_none


class ValidateImageStep:
    """Re-validates the *stored* original so every later step works from verified bytes.

    Confirms the object exists, its SHA-256 matches the record, and it still
    passes the same checks applied at upload (format, dimensions, decodability).
    Publishes ``ctx.artifacts["image"]`` (ValidatedImage) for downstream steps.
    """

    name = "validate"
    critical = True

    async def run(self, ctx: PipelineContext) -> StepOutcome:
        if ctx.file is None:
            raise StepFailedError("NO_FILE", "The analysis has no stored file.")
        try:
            data, _ = await ctx.storage.get(ctx.file.object_key)
        except ObjectNotFoundError as exc:
            raise StepFailedError(
                "FILE_MISSING", "The stored original could not be found."
            ) from exc

        image = validate_image(
            data,
            max_bytes=ctx.settings.max_upload_bytes,
            max_pixels=ctx.settings.max_image_pixels,
        )
        if image.sha256 != ctx.file.sha256:
            raise StepFailedError(
                "HASH_MISMATCH", "The stored file does not match the recorded SHA-256."
            )

        ctx.artifacts["image"] = image
        return StepOutcome.ok(
            format=image.pil_format,
            mime_type=image.mime_type,
            width=image.width,
            height=image.height,
            size_bytes=image.size_bytes,
            sha256=image.sha256,
            frames=image.frames,
        )


class HashImageStep:
    """Content (SHA-256, MD5) and perceptual (aHash, dHash, pHash) hashes of the verified bytes.

    Deterministic and local, so it is a core step. Values are recorded in the
    step details now; T015 persists them to ``image_fingerprints`` for matching.
    """

    name = "hashing"
    critical = True

    async def run(self, ctx: PipelineContext) -> StepOutcome:
        image = ctx.artifacts.get("image")
        if image is None:
            raise StepFailedError("NO_VERIFIED_IMAGE", "Validation did not publish an image.")
        hashes = compute_hashes(image.data)
        ctx.artifacts["hashes"] = hashes
        return StepOutcome.ok(
            sha256=hashes.sha256,
            md5=hashes.md5,
            ahash=hashes.ahash,
            dhash=hashes.dhash,
            phash=hashes.phash,
            algorithm_version="v1",  # bump if any hash definition changes
        )


class ExtractMetadataStep:
    """EXIF/XMP/IPTC/ICC via the configured engine. Raw groups are preserved verbatim.

    Non-critical: an image without metadata is a normal, fully valid outcome
    (recorded as UNKNOWN downstream), and an engine failure must not sink the
    deterministic steps that already ran.
    """

    name = "metadata"
    critical = False

    async def run(self, ctx: PipelineContext) -> StepOutcome:
        image = ctx.artifacts.get("image")
        if image is None:
            raise StepFailedError("NO_VERIFIED_IMAGE", "Validation did not publish an image.")
        extractor: MetadataExtractor = ctx.providers.get("metadata") or build_metadata_extractor(
            ctx.settings
        )
        try:
            raw = await extractor.extract(image.data)
        except MetadataExtractionError as exc:
            raise StepFailedError("METADATA_ENGINE_FAILED", str(exc)) from exc

        normalized = normalize_metadata(raw)
        row = ImageMetadata(
            analysis_id=ctx.analysis.id,
            engine=raw.engine,
            engine_version=raw.engine_version,
            exif_json=raw.group("EXIF") or None,
            xmp_json=raw.group("XMP") or None,
            iptc_json=raw.group("IPTC") or None,
            icc_json=raw.group("ICC_Profile") or None,
            raw_json=raw.groups,
            normalized_json=normalized.to_json(),
            software=normalized.software,
            camera_make=normalized.camera_make,
            camera_model=normalized.camera_model,
            captured_at=to_utc_or_none(normalized.captured_at),
            modified_at=to_utc_or_none(normalized.modified_at),
        )
        await AnalysisRepository(ctx.session).replace_metadata(row)
        ctx.artifacts["metadata"] = normalized
        return StepOutcome.ok(
            engine=raw.engine,
            engine_version=raw.engine_version,
            tag_counts=normalized.tag_counts,
            has_exif=normalized.has_exif,
            has_xmp=normalized.has_xmp,
            has_iptc=normalized.has_iptc,
            has_icc=normalized.has_icc,
            gps_present=normalized.gps_present,
            warnings=normalized.warnings[:20],
        )


def image_pipeline_steps() -> list[ValidateImageStep | HashImageStep | ExtractMetadataStep]:
    """Ordered steps for an image analysis. Later tasks append C2PA, forensics, ..."""
    return [ValidateImageStep(), HashImageStep(), ExtractMetadataStep()]
