"""Usage endpoints: the caller's own counters, storage and limits. Never another user's."""

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, UsageSvc
from app.schemas.usage import UsageHistoryResponse, UsagePeriodResponse
from app.services.usage import UsageSnapshot

router = APIRouter(prefix="/usage")


def _period(s: UsageSnapshot) -> UsagePeriodResponse:
    return UsagePeriodResponse(
        period_start=s.period_start,
        analyses_count=s.analyses_count,
        image_count=s.image_count,
        text_count=s.text_count,
        reports_count=s.reports_count,
        provider_calls_count=s.provider_calls_count,
        provider_cost=round(s.provider_cost, 6),
        storage_bytes_period=s.storage_bytes_period,
        current_storage_bytes=s.current_storage_bytes,
        analysis_limit=s.analysis_limit,
        storage_limit_bytes=s.storage_limit_bytes,
        provider_cost_limit=s.provider_cost_limit,
        analyses_remaining=s.analyses_remaining,
        storage_remaining_bytes=s.storage_remaining_bytes,
        provider_budget_remaining=s.provider_budget_remaining,
    )


@router.get("", response_model=UsagePeriodResponse)
async def current_usage(user: CurrentUser, usage: UsageSvc) -> UsagePeriodResponse:
    return _period(await usage.snapshot(user.id))


@router.get("/history", response_model=UsageHistoryResponse)
async def usage_history(
    user: CurrentUser, usage: UsageSvc, months: int = Query(default=6, ge=1, le=24)
) -> UsageHistoryResponse:
    return UsageHistoryResponse(
        periods=[_period(s) for s in await usage.history(user.id, months=months)]
    )
