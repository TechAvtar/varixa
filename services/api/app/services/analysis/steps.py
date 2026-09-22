"""Concrete pipeline steps for image analyses. Each is small and independently testable."""

from app.providers.storage.base import ObjectNotFoundError
from app.services.analysis.pipeline import PipelineContext, StepFailedError, StepOutcome
from app.services.image import validate_image
from app.services.image.hashing import compute_hashes


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


def image_pipeline_steps() -> list[ValidateImageStep | HashImageStep]:
    """Ordered steps for an image analysis. Later tasks append metadata, C2PA, forensics, ..."""
    return [ValidateImageStep(), HashImageStep()]
