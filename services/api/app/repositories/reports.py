"""Persistence for rendered reports."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Report


class ReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, report_id: uuid.UUID) -> Report | None:
        return (
            await self._session.execute(select(Report).where(Report.id == report_id))
        ).scalar_one_or_none()

    async def list_for_analysis(self, analysis_id: uuid.UUID) -> Sequence[Report]:
        stmt = (
            select(Report)
            .where(Report.analysis_id == analysis_id)
            .order_by(Report.created_at.desc(), Report.id)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def list_object_keys(self, analysis_id: uuid.UUID) -> list[str]:
        stmt = select(Report.object_key).where(
            Report.analysis_id == analysis_id, Report.object_key.is_not(None)
        )
        return [k for k in (await self._session.execute(stmt)).scalars().all() if k]

    async def mark_expired(self, analysis_id: uuid.UUID, now: datetime) -> int:
        """Report files were removed by retention: keep the metadata, drop the key."""
        stmt = (
            update(Report)
            .where(Report.analysis_id == analysis_id, Report.object_key.is_not(None))
            .values(object_key=None, status="expired")
        )
        result = await self._session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)

    async def add(self, report: Report) -> Report:
        self._session.add(report)
        await self._session.flush()
        return report
