"""Concrete pipeline steps for image analyses. Each is small and independently testable."""

from app.providers.storage.base import ObjectNotFoundError
from app.services.analysis.pipeline import PipelineContext, StepFailedError, StepOutcome
from app.services.image import validate_image


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


def image_pipeline_steps() -> list[ValidateImageStep]:
    """Ordered steps for an image analysis. Later tasks append metadata, C2PA, forensics, ..."""
    return [ValidateImageStep()]
