import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Analysis, AnalysisFile, AnalysisStep, ImageMetadata


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
        stmt = select(AnalysisFile.object_key).where(AnalysisFile.analysis_id == analysis_id)
        return list((await self._session.execute(stmt)).scalars().all())

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

    async def replace_metadata(self, metadata: ImageMetadata) -> ImageMetadata:
        """Idempotent: a re-run replaces the previous row for the analysis."""
        await self._session.execute(
            delete(ImageMetadata).where(ImageMetadata.analysis_id == metadata.analysis_id)
        )
        self._session.add(metadata)
        await self._session.flush()
        return metadata
