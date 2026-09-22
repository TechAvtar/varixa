from datetime import date

from pydantic import BaseModel


class UsagePeriodResponse(BaseModel):
    """Activity in one calendar month plus the limits in force (0 = unlimited)."""

    period_start: date
    analyses_count: int
    image_count: int
    text_count: int
    reports_count: int
    provider_calls_count: int
    provider_cost: float
    storage_bytes_period: int
    # Bytes currently held for the user (live, unpurged originals, reports, artifacts).
    current_storage_bytes: int
    analysis_limit: int
    storage_limit_bytes: int
    provider_cost_limit: float
    analyses_remaining: int | None
    storage_remaining_bytes: int | None
    provider_budget_remaining: float | None


class UsageHistoryResponse(BaseModel):
    periods: list[UsagePeriodResponse]
