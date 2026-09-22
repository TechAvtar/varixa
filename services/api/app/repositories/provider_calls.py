import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ProviderCall


class ProviderCallRepository:
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
