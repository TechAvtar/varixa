import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AIDetection,
    Analysis,
    AnalysisFile,
    AnalysisStep,
    ImageFingerprints,
    ImageForensics,
    ImageMetadata,
    ImageProvenance,
    SourceMatch,
    SourceSearchRun,
    TextAnalysis,
    TextFingerprints,
)


class AnalysisRepository:
    """Persistence for analyses. Soft-deleted rows are invisible to every read."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, analysis_id: uuid.UUID) -> Analysis | None:
        stmt = (
            select(Analysis)
            .where(Analysis.id == analysis_id, Analysis.deleted_at.is_(None))
            .options(selectinload(Analysis.files), selectinload(Analysis.steps))
            .execution_options(populate_existing=True)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(
        self, user_id: uuid.UUID, *, offset: int, limit: int
    ) -> tuple[Sequence[Analysis], int]:
        base = select(Analysis).where(Analysis.user_id == user_id, Analysis.deleted_at.is_(None))
        total = (
            await self._session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        stmt = (
            base.options(selectinload(Analysis.files), selectinload(Analysis.steps))
            .order_by(Analysis.created_at.desc(), Analysis.id.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return rows, total

    async def count_by_type_for_user(self, user_id: uuid.UUID) -> dict[str, int]:
        stmt = (
            select(Analysis.type, func.count())
            .where(Analysis.user_id == user_id, Analysis.deleted_at.is_(None))
            .group_by(Analysis.type)
        )
        return {row[0]: row[1] for row in (await self._session.execute(stmt)).all()}

    async def list_object_keys(self, analysis_id: uuid.UUID) -> list[str]:
        """Every stored object for the analysis: originals plus generated artifacts."""
        stmt = select(AnalysisFile.object_key).where(AnalysisFile.analysis_id == analysis_id)
        keys = list((await self._session.execute(stmt)).scalars().all())
        forensics = await self.get_forensics(analysis_id)
        for artifact in (forensics.artifacts_json or []) if forensics else []:
            key = artifact.get("object_key")
            if isinstance(key, str) and key not in keys:
                keys.append(key)
        return keys

    async def add(self, analysis: Analysis) -> Analysis:
        self._session.add(analysis)
        await self._session.flush()
        return analysis

    async def add_file(self, file: AnalysisFile) -> AnalysisFile:
        self._session.add(file)
        await self._session.flush()
        return file

    async def add_step(self, step: AnalysisStep) -> AnalysisStep:
        self._session.add(step)
        await self._session.flush()
        return step

    async def get_metadata(self, analysis_id: uuid.UUID) -> ImageMetadata | None:
        stmt = select(ImageMetadata).where(ImageMetadata.analysis_id == analysis_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_fingerprints(self, analysis_id: uuid.UUID) -> ImageFingerprints | None:
        stmt = select(ImageFingerprints).where(ImageFingerprints.analysis_id == analysis_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def replace_fingerprints(self, fp: ImageFingerprints) -> ImageFingerprints:
        await self._session.execute(
            delete(ImageFingerprints).where(ImageFingerprints.analysis_id == fp.analysis_id)
        )
        self._session.add(fp)
        await self._session.flush()
        return fp

    async def list_user_fingerprints(
        self, user_id: uuid.UUID, *, exclude_analysis_id: uuid.UUID, limit: int = 5000
    ) -> Sequence[tuple[ImageFingerprints, Analysis]]:
        """Fingerprints of the user's other live analyses (candidates for similarity)."""
        stmt = (
            select(ImageFingerprints, Analysis)
            .join(Analysis, Analysis.id == ImageFingerprints.analysis_id)
            .where(
                Analysis.user_id == user_id,
                Analysis.deleted_at.is_(None),
                Analysis.id != exclude_analysis_id,
            )
            .order_by(Analysis.created_at.desc())
            .limit(limit)
        )
        return [(row[0], row[1]) for row in (await self._session.execute(stmt)).all()]

    async def get_text_analysis(self, analysis_id: uuid.UUID) -> TextAnalysis | None:
        stmt = select(TextAnalysis).where(TextAnalysis.analysis_id == analysis_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def replace_text_analysis(self, row: TextAnalysis) -> TextAnalysis:
        await self._session.execute(
            delete(TextAnalysis).where(TextAnalysis.analysis_id == row.analysis_id)
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_text_fingerprints(self, analysis_id: uuid.UUID) -> TextFingerprints | None:
        stmt = select(TextFingerprints).where(TextFingerprints.analysis_id == analysis_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def replace_text_fingerprints(self, fp: TextFingerprints) -> TextFingerprints:
        await self._session.execute(
            delete(TextFingerprints).where(TextFingerprints.analysis_id == fp.analysis_id)
        )
        self._session.add(fp)
        await self._session.flush()
        return fp

    async def list_user_text_fingerprints(
        self, user_id: uuid.UUID, *, exclude_analysis_id: uuid.UUID, limit: int = 5000
    ) -> Sequence[tuple[TextFingerprints, Analysis]]:
        stmt = (
            select(TextFingerprints, Analysis)
            .join(Analysis, Analysis.id == TextFingerprints.analysis_id)
            .where(
                Analysis.user_id == user_id,
                Analysis.deleted_at.is_(None),
                Analysis.id != exclude_analysis_id,
            )
            .order_by(Analysis.created_at.desc())
            .limit(limit)
        )
        return [(row[0], row[1]) for row in (await self._session.execute(stmt)).all()]

    async def get_ai_detection(self, analysis_id: uuid.UUID) -> AIDetection | None:
        stmt = select(AIDetection).where(AIDetection.analysis_id == analysis_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def replace_ai_detection(self, row: AIDetection) -> AIDetection:
        await self._session.execute(
            delete(AIDetection).where(AIDetection.analysis_id == row.analysis_id)
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_source_search(
        self, analysis_id: uuid.UUID
    ) -> tuple[SourceSearchRun | None, Sequence[SourceMatch]]:
        run = (
            await self._session.execute(
                select(SourceSearchRun).where(SourceSearchRun.analysis_id == analysis_id)
            )
        ).scalar_one_or_none()
        matches = (
            (
                await self._session.execute(
                    select(SourceMatch)
                    .where(SourceMatch.analysis_id == analysis_id)
                    .order_by(SourceMatch.rank)
                )
            )
            .scalars()
            .all()
        )
        return run, matches

    async def replace_source_search(self, run: SourceSearchRun, matches: list[SourceMatch]) -> None:
        await self._session.execute(
            delete(SourceMatch).where(SourceMatch.analysis_id == run.analysis_id)
        )
        await self._session.execute(
            delete(SourceSearchRun).where(SourceSearchRun.analysis_id == run.analysis_id)
        )
        self._session.add(run)
        self._session.add_all(matches)
        await self._session.flush()

    async def get_provenance(self, analysis_id: uuid.UUID) -> ImageProvenance | None:
        stmt = select(ImageProvenance).where(ImageProvenance.analysis_id == analysis_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def replace_provenance(self, provenance: ImageProvenance) -> ImageProvenance:
        await self._session.execute(
            delete(ImageProvenance).where(ImageProvenance.analysis_id == provenance.analysis_id)
        )
        self._session.add(provenance)
        await self._session.flush()
        return provenance

    async def get_forensics(self, analysis_id: uuid.UUID) -> ImageForensics | None:
        stmt = select(ImageForensics).where(ImageForensics.analysis_id == analysis_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def upsert_forensics(self, analysis_id: uuid.UUID, **columns: Any) -> ImageForensics:
        """Set the given ``*_json`` columns on the analysis' forensics row, creating it if needed.

        Each forensic method owns one column, so re-running one method never discards another's.
        """
        row = await self.get_forensics(analysis_id)
        if row is None:
            row = ImageForensics(analysis_id=analysis_id)
            self._session.add(row)
        for name, value in columns.items():
            setattr(row, name, value)
        await self._session.flush()
        return row

    async def replace_metadata(self, metadata: ImageMetadata) -> ImageMetadata:
        """Idempotent: a re-run replaces the previous row for the analysis."""
        await self._session.execute(
            delete(ImageMetadata).where(ImageMetadata.analysis_id == metadata.analysis_id)
        )
        self._session.add(metadata)
        await self._session.flush()
        return metadata
