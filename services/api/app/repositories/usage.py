"""Persistence for usage counters and storage accounting."""

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Analysis, AnalysisFile, ImageForensics, Report, Usage

COUNTER_COLUMNS = frozenset(
    {
        "analyses_count",
        "image_count",
        "text_count",
        "reports_count",
        "provider_calls_count",
        "provider_cost",
        "storage_bytes",
    }
)


class UsageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID, period_start: date) -> Usage | None:
        stmt = select(Usage).where(Usage.user_id == user_id, Usage.period_start == period_start)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_or_create(self, user_id: uuid.UUID, period_start: date) -> Usage:
        row = await self.get(user_id, period_start)
        if row is None:
            row = Usage(user_id=user_id, period_start=period_start)
            self._session.add(row)
            await self._session.flush()
        return row

    async def increment(self, user_id: uuid.UUID, period_start: date, **deltas: Any) -> None:
        """Atomic ``counter = counter + delta`` so concurrent requests never lose updates."""
        bad = set(deltas) - COUNTER_COLUMNS
        if bad:
            raise ValueError(f"unknown usage counters: {sorted(bad)}")
        await self.get_or_create(user_id, period_start)
        values = {name: getattr(Usage, name) + delta for name, delta in deltas.items() if delta}
        if not values:
            return
        await self._session.execute(
            update(Usage)
            .where(Usage.user_id == user_id, Usage.period_start == period_start)
            .values(**values)
        )
        await self._session.flush()

    async def list_for_user(self, user_id: uuid.UUID, *, limit: int = 12) -> Sequence[Usage]:
        stmt = (
            select(Usage)
            .where(Usage.user_id == user_id)
            .order_by(Usage.period_start.desc())
            .limit(limit)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def current_storage_bytes(self, user_id: uuid.UUID) -> int:
        """Bytes currently held for the user: originals, reports and forensic artifacts.

        Computed from live rows (not deleted, content not purged) so it is always accurate.
        """
        live = (
            select(Analysis.id)
            .where(
                Analysis.user_id == user_id,
                Analysis.deleted_at.is_(None),
                Analysis.content_purged_at.is_(None),
            )
            .subquery()
        )
        files = await self._session.scalar(
            select(func.coalesce(func.sum(AnalysisFile.size_bytes), 0)).where(
                AnalysisFile.analysis_id.in_(select(live.c.id))
            )
        )
        reports = await self._session.scalar(
            select(func.coalesce(func.sum(Report.size_bytes), 0)).where(
                Report.analysis_id.in_(select(live.c.id)), Report.object_key.is_not(None)
            )
        )
        artifacts = 0
        rows = (
            await self._session.execute(
                select(ImageForensics.artifacts_json).where(
                    ImageForensics.analysis_id.in_(select(live.c.id))
                )
            )
        ).scalars()
        for entries in rows:
            for a in entries or []:
                size = a.get("size_bytes") if isinstance(a, dict) else None
                if isinstance(size, int):
                    artifacts += size
        return int(files or 0) + int(reports or 0) + artifacts
