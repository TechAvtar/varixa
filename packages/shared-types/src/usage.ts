/** Mirrors `app/schemas/usage.py`. Limits of 0 mean unlimited. */

export interface UsagePeriodResponse {
  period_start: string;
  analyses_count: number;
  image_count: number;
  text_count: number;
  reports_count: number;
  provider_calls_count: number;
  provider_cost: number;
  storage_bytes_period: number;
  /** Bytes currently held for the user (live, unpurged originals, reports, artifacts). */
  current_storage_bytes: number;
  analysis_limit: number;
  storage_limit_bytes: number;
  provider_cost_limit: number;
  analyses_remaining: number | null;
  storage_remaining_bytes: number | null;
  provider_budget_remaining: number | null;
}

export interface UsageHistoryResponse {
  periods: UsagePeriodResponse[];
}
