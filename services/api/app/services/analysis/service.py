"""Analysis lifecycle: create, read (owner-scoped), status transitions, soft delete."""

import logging
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.enums import AnalysisStatus, AnalysisType
from app.models import Analysis, AnalysisFile, ImageMetadata, User
from app.providers.storage.base import ObjectStorage
from app.repositories.analysis import AnalysisRepository
from app.services import storage_keys
from app.services.authorization import assert_owns_analysis
from app.services.image import validate_image
from app.utils.errors import ConflictError

log = logging.getLogger("verixa.analysis")

MAX_ERROR_MESSAGE = 1000
MAX_TITLE = 300
MAX_FILENAME = 255
_FILENAME_UNSAFE = re.compile(r"[\x00-\x1f\x7f/\\]")

# Legal status transitions. Terminal states have no successors.
_TRANSITIONS: dict[str, frozenset[str]] = {
    AnalysisStatus.QUEUED: frozenset({AnalysisStatus.PROCESSING, AnalysisStatus.FAILED}),
    AnalysisStatus.PROCESSING: frozenset({AnalysisStatus.COMPLETED, AnalysisStatus.FAILED}),
    AnalysisStatus.COMPLETED: frozenset(),
    AnalysisStatus.FAILED: frozenset(),
}


def _clean_title(title: str | None) -> str | None:
    return (title or "").strip()[:MAX_TITLE] or None


def _clean_filename(name: str | None) -> str | None:
    if not name:
        return None
    cleaned = _FILENAME_UNSAFE.sub("", name).strip()
    return cleaned[:MAX_FILENAME] or None


class AnalysisService:
    def __init__(self, session: AsyncSession, storage: ObjectStorage, settings: Settings) -> None:
        self._db = session
        self._storage = storage
        self._settings = settings
        self._analyses = AnalysisRepository(session)

    # -- create / read ------------------------------------------------------------

    async def create(self, user: User, *, type: AnalysisType, title: str | None) -> Analysis:
        analysis = Analysis(
            user_id=user.id, type=type, status=AnalysisStatus.QUEUED, title=_clean_title(title)
        )
        await self._analyses.add(analysis)
        await self._db.commit()
        return analysis

    async def create_image_analysis(
        self, user: User, *, data: bytes, filename: str | None, title: str | None
    ) -> Analysis:
        """Validate an untrusted upload, store the original privately, create the record.

        Validation happens first so a bad file never leaves a row behind. The row
        is committed only after the object is stored; a storage failure rolls back.
        """
        image = validate_image(
            data,
            max_bytes=self._settings.max_upload_bytes,
            max_pixels=self._settings.max_image_pixels,
        )
        safe_name = _clean_filename(filename)
        analysis = Analysis(
            user_id=user.id,
            type=AnalysisType.IMAGE,
            status=AnalysisStatus.QUEUED,
            title=_clean_title(title) or safe_name,
        )
        await self._analyses.add(analysis)

        key = storage_keys.upload_key(user.id, analysis.id, image.sha256, image.extension)
        try:
            await self._storage.put(key, image.data, content_type=image.mime_type)
        except Exception:
            await self._db.rollback()
            log.exception("upload storage failed analysis_id=%s", analysis.id)
            raise

        await self._analyses.add_file(
            AnalysisFile(
                analysis_id=analysis.id,
                object_key=key,
                original_filename=safe_name,
                mime_type=image.mime_type,
                size_bytes=image.size_bytes,
                sha256=image.sha256,
                width=image.width,
                height=image.height,
            )
        )
        await self._db.commit()
        return analysis

    async def get_owned(self, user: User, analysis_id: uuid.UUID) -> Analysis:
        analysis = await self._analyses.get(analysis_id)
        assert_owns_analysis(user, analysis)
        assert analysis is not None  # narrowed by the ownership check
        return analysis

    async def list_owned(
        self, user: User, *, page: int, page_size: int
    ) -> tuple[Sequence[Analysis], int]:
        return await self._analyses.list_for_user(
            user.id, offset=(page - 1) * page_size, limit=page_size
        )

    async def get_metadata(self, user: User, analysis_id: uuid.UUID) -> ImageMetadata | None:
        await self.get_owned(user, analysis_id)  # ownership first; existence never leaks
        return await self._analyses.get_metadata(analysis_id)

    async def counts(self, user: User) -> dict[str, int]:
        by_type = await self._analyses.count_by_type_for_user(user.id)
        image = by_type.get(AnalysisType.IMAGE, 0)
        text = by_type.get(AnalysisType.TEXT, 0)
        return {"total": image + text, "image": image, "text": text}

    # -- status transitions -----------------------------------------------------

    async def mark_processing(self, analysis: Analysis) -> Analysis:
        return await self._transition(analysis, AnalysisStatus.PROCESSING)

    async def mark_completed(self, analysis: Analysis) -> Analysis:
        analysis.completed_at = datetime.now(UTC)
        return await self._transition(analysis, AnalysisStatus.COMPLETED)

    async def mark_failed(self, analysis: Analysis, *, code: str, message: str) -> Analysis:
        analysis.error_code = code[:64]
        analysis.error_message = message[:MAX_ERROR_MESSAGE]
        analysis.completed_at = datetime.now(UTC)
        return await self._transition(analysis, AnalysisStatus.FAILED)

    async def _transition(self, analysis: Analysis, new_status: AnalysisStatus) -> Analysis:
        if new_status not in _TRANSITIONS[analysis.status]:
            raise ConflictError(
                f"Cannot move analysis from '{analysis.status}' to '{new_status}'.",
                code="INVALID_TRANSITION",
            )
        analysis.status = new_status
        await self._db.commit()
        return analysis

    # -- delete -------------------------------------------------------------------

    async def soft_delete(self, user: User, analysis_id: uuid.UUID) -> None:
        """Mark deleted, then remove stored originals. Reads hide the row immediately."""
        analysis = await self.get_owned(user, analysis_id)
        analysis.deleted_at = datetime.now(UTC)
        await self._db.commit()

        failures = 0
        for key in await self._analyses.list_object_keys(analysis.id):
            try:
                await self._storage.delete(key)
            except Exception:  # storage failures must not resurrect the record
                failures += 1
        if failures:
            # Retention sweeper (T037) retries; keys are never logged.
            log.warning(
                "storage cleanup incomplete analysis_id=%s failed_objects=%d", analysis.id, failures
            )
