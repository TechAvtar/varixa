"""Analysis lifecycle: create, read (owner-scoped), status transitions, soft delete."""

import hashlib
import logging
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.enums import AnalysisStatus, AnalysisType
from app.models import (
    AIDetection,
    Analysis,
    AnalysisFile,
    ImageFingerprints,
    ImageMetadata,
    ImageProvenance,
    ProviderCall,
    SourceMatch,
    SourceSearchRun,
    TextAnalysis,
    TextFingerprints,
    User,
)
from app.providers.storage.base import ObjectStorage
from app.repositories.analysis import AnalysisRepository
from app.repositories.provider_calls import ProviderCallRepository
from app.services import storage_keys
from app.services.authorization import assert_owns_analysis
from app.services.image import validate_image
from app.services.image.similarity import SimilarityMatch, compare
from app.services.image.validation import ImageTooLargeError
from app.services.text.fingerprints import estimate_jaccard
from app.utils.errors import ConflictError, ValidationError

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

    async def create_text_analysis(self, user: User, *, text: str, title: str | None) -> Analysis:
        """Store the pasted text privately, exactly as received, and create the record."""
        if not text.strip():
            raise ValidationError("The text is empty.")
        if len(text) > self._settings.max_text_chars:
            raise ImageTooLargeError(
                f"The text exceeds the maximum of {self._settings.max_text_chars:,} characters."
            )
        data = text.encode("utf-8")
        sha256 = hashlib.sha256(data).hexdigest()
        first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        analysis = Analysis(
            user_id=user.id,
            type=AnalysisType.TEXT,
            status=AnalysisStatus.QUEUED,
            title=_clean_title(title) or _clean_title(first_line[:120]),
        )
        await self._analyses.add(analysis)
        key = storage_keys.upload_key(user.id, analysis.id, sha256, "txt")
        try:
            await self._storage.put(key, data, content_type="text/plain; charset=utf-8")
        except Exception:
            await self._db.rollback()
            log.exception("text storage failed analysis_id=%s", analysis.id)
            raise
        await self._analyses.add_file(
            AnalysisFile(
                analysis_id=analysis.id,
                object_key=key,
                original_filename=None,
                mime_type="text/plain",
                size_bytes=len(data),
                sha256=sha256,
            )
        )
        await self._db.commit()
        return analysis

    async def get_text_analysis(self, user: User, analysis_id: uuid.UUID) -> TextAnalysis | None:
        await self.get_owned(user, analysis_id)
        return await self._analyses.get_text_analysis(analysis_id)

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

    async def get_fingerprints(
        self, user: User, analysis_id: uuid.UUID
    ) -> ImageFingerprints | None:
        await self.get_owned(user, analysis_id)
        return await self._analyses.get_fingerprints(analysis_id)

    async def find_similar(
        self, user: User, fingerprints: ImageFingerprints
    ) -> list[tuple[Analysis, SimilarityMatch]]:
        """Exact and near duplicates among the *same user's* live analyses, best first."""
        threshold = self._settings.fingerprint_near_threshold
        candidates = await self._analyses.list_user_fingerprints(
            user.id, exclude_analysis_id=fingerprints.analysis_id
        )
        matches: list[tuple[Analysis, SimilarityMatch]] = []
        for other_fp, other_analysis in candidates:
            match = compare(fingerprints, other_fp, near_threshold=threshold)
            if match is not None:
                matches.append((other_analysis, match))
        matches.sort(key=lambda m: (m[1].score, m[0].created_at), reverse=False)
        return matches

    async def get_text_fingerprints(
        self, user: User, analysis_id: uuid.UUID
    ) -> TextFingerprints | None:
        await self.get_owned(user, analysis_id)
        return await self._analyses.get_text_fingerprints(analysis_id)

    async def find_similar_texts(
        self, user: User, fp: TextFingerprints
    ) -> list[tuple[Analysis, str, float]]:
        """(analysis, relation, estimated_jaccard) among the user's live texts, strongest first."""
        threshold = self._settings.text_near_threshold
        matches: list[tuple[Analysis, str, float]] = []
        candidates = await self._analyses.list_user_text_fingerprints(
            user.id, exclude_analysis_id=fp.analysis_id
        )
        for other, analysis in candidates:
            jaccard = estimate_jaccard(list(fp.minhash_json), list(other.minhash_json))
            if other.sha256 == fp.sha256:
                relation = "exact"
            elif other.normalized_sha256 == fp.normalized_sha256:
                relation = "normalized"
            elif other.canonical_sha256 == fp.canonical_sha256:
                relation = "canonical"
            elif jaccard >= threshold:
                relation = "near"
            else:
                continue
            matches.append((analysis, relation, jaccard))
        rank = {"exact": 0, "normalized": 1, "canonical": 2, "near": 3}
        matches.sort(key=lambda m: (rank[m[1]], -m[2]))
        return matches

    async def get_ai_detection(self, user: User, analysis_id: uuid.UUID) -> AIDetection | None:
        await self.get_owned(user, analysis_id)
        return await self._analyses.get_ai_detection(analysis_id)

    async def get_source_search(
        self, user: User, analysis_id: uuid.UUID
    ) -> tuple[SourceSearchRun | None, Sequence[SourceMatch]]:
        await self.get_owned(user, analysis_id)
        return await self._analyses.get_source_search(analysis_id)

    async def list_provider_calls(
        self, user: User, analysis_id: uuid.UUID
    ) -> tuple[Sequence[ProviderCall], float]:
        await self.get_owned(user, analysis_id)
        repo = ProviderCallRepository(self._db)
        return (
            await repo.list_for_analysis(analysis_id),
            await repo.total_cost_for_analysis(analysis_id),
        )

    async def get_provenance(self, user: User, analysis_id: uuid.UUID) -> ImageProvenance | None:
        await self.get_owned(user, analysis_id)
        return await self._analyses.get_provenance(analysis_id)

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
