"""Usage accounting and limits.

Counters are per user and calendar month (UTC). Limits are settings; ``0`` means
unlimited. Creation is refused with 429 ``USAGE_LIMIT_EXCEEDED`` when the monthly
analysis count or the current storage occupancy would be exceeded, and paid provider
steps are skipped once the month's provider budget is spent, so a runaway account can
never bill more than configured.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Usage
from app.repositories.usage import UsageRepository
from app.utils.errors import LimitExceededError


def period_start(now: datetime | None = None) -> date:
    now = now or datetime.now(UTC)
    return now.astimezone(UTC).date().replace(day=1)


@dataclass(frozen=True)
class UsageSnapshot:
    period_start: date
    analyses_count: int
    image_count: int
    text_count: int
    reports_count: int
    provider_calls_count: int
    provider_cost: float
    storage_bytes_period: int
    current_storage_bytes: int
    analysis_limit: int
    storage_limit_bytes: int
    provider_cost_limit: float

    @property
    def analyses_remaining(self) -> int | None:
        if self.analysis_limit <= 0:
            return None
        return max(0, self.analysis_limit - self.analyses_count)

    @property
    def storage_remaining_bytes(self) -> int | None:
        if self.storage_limit_bytes <= 0:
            return None
        return max(0, self.storage_limit_bytes - self.current_storage_bytes)

    @property
    def provider_budget_remaining(self) -> float | None:
        if self.provider_cost_limit <= 0:
            return None
        return max(0.0, round(self.provider_cost_limit - self.provider_cost, 6))


class UsageService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._db = session
        self._settings = settings
        self._usage = UsageRepository(session)

    # -- recording ------------------------------------------------------------------------------

    async def record_analysis(
        self, user_id: uuid.UUID, *, analysis_type: str, size_bytes: int
    ) -> None:
        await self._usage.increment(
            user_id,
            period_start(),
            analyses_count=1,
            image_count=1 if analysis_type == "image" else 0,
            text_count=1 if analysis_type == "text" else 0,
            storage_bytes=max(0, size_bytes),
        )

    async def record_storage(self, user_id: uuid.UUID, size_bytes: int) -> None:
        await self._usage.increment(user_id, period_start(), storage_bytes=max(0, size_bytes))

    async def record_report(self, user_id: uuid.UUID, size_bytes: int) -> None:
        await self._usage.increment(
            user_id, period_start(), reports_count=1, storage_bytes=max(0, size_bytes)
        )

    async def record_provider_call(self, user_id: uuid.UUID, cost: float | None) -> None:
        await self._usage.increment(
            user_id, period_start(), provider_calls_count=1, provider_cost=float(cost or 0.0)
        )

    # -- reading --------------------------------------------------------------------------------

    async def snapshot(self, user_id: uuid.UUID, *, now: datetime | None = None) -> UsageSnapshot:
        start = period_start(now)
        row = await self._usage.get(user_id, start)
        return self._snapshot_from(row, start, await self._usage.current_storage_bytes(user_id))

    async def history(self, user_id: uuid.UUID, *, months: int = 6) -> list[UsageSnapshot]:
        current = await self._usage.current_storage_bytes(user_id)
        rows = await self._usage.list_for_user(user_id, limit=months)
        return [self._snapshot_from(r, r.period_start, current) for r in rows]

    def _snapshot_from(self, row: Usage | None, start: date, current: int) -> UsageSnapshot:
        s = self._settings
        return UsageSnapshot(
            period_start=start,
            analyses_count=row.analyses_count if row else 0,
            image_count=row.image_count if row else 0,
            text_count=row.text_count if row else 0,
            reports_count=row.reports_count if row else 0,
            provider_calls_count=row.provider_calls_count if row else 0,
            provider_cost=float(row.provider_cost) if row else 0.0,
            storage_bytes_period=row.storage_bytes if row else 0,
            current_storage_bytes=current,
            analysis_limit=s.usage_monthly_analysis_limit,
            storage_limit_bytes=s.usage_storage_limit_bytes,
            provider_cost_limit=s.usage_monthly_provider_cost_limit,
        )

    # -- limits ---------------------------------------------------------------------------------

    async def assert_can_create(self, user_id: uuid.UUID, *, incoming_bytes: int) -> None:
        """Raise ``LimitExceededError`` when a new analysis would breach a configured limit."""
        snap = await self.snapshot(user_id)
        if snap.analysis_limit > 0 and snap.analyses_count >= snap.analysis_limit:
            raise LimitExceededError(
                f"Monthly analysis limit of {snap.analysis_limit} reached; it resets on the 1st.",
                code="USAGE_LIMIT_EXCEEDED",
            )
        if (
            snap.storage_limit_bytes > 0
            and snap.current_storage_bytes + max(0, incoming_bytes) > snap.storage_limit_bytes
        ):
            raise LimitExceededError(
                "Storage limit reached; delete analyses or let content expire to free space.",
                code="STORAGE_LIMIT_EXCEEDED",
            )

    async def provider_budget_exhausted(self, user_id: uuid.UUID) -> bool:
        snap = await self.snapshot(user_id)
        return snap.provider_cost_limit > 0 and snap.provider_cost >= snap.provider_cost_limit
