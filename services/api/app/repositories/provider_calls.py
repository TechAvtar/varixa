import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ProviderCall


class ProviderCallRepository:
    async def purge_responses_before(self, cutoff: datetime, now: datetime) -> int:
        """Clear raw response/error payloads of calls older than ``cutoff``; keep the audit row."""
        stmt = (
            update(ProviderCall)
            .where(
                ProviderCall.created_at < cutoff,
                ProviderCall.purged_at.is_(None),
                or_(ProviderCall.response_json.is_not(None), ProviderCall.error_json.is_not(None)),
            )
            .values(response_json=None, error_json=None, purged_at=now)
        )
        result = await self._session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, call: ProviderCall) -> ProviderCall:
        self._session.add(call)
        await self._session.flush()
        return call

    async def list_for_analysis(self, analysis_id: uuid.UUID) -> Sequence[ProviderCall]:
        stmt = (
            select(ProviderCall)
            .where(ProviderCall.analysis_id == analysis_id)
            .order_by(ProviderCall.created_at, ProviderCall.id)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def total_cost_for_analysis(self, analysis_id: uuid.UUID) -> float:
        stmt = select(func.coalesce(func.sum(ProviderCall.estimated_cost), 0)).where(
            ProviderCall.analysis_id == analysis_id
        )
        value = (await self._session.execute(stmt)).scalar_one()
        return float(value or 0)
