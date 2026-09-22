/** Mirrors `app/schemas/provider_calls.py`. Audit trail of engine/provider calls per analysis. */

export type ProviderCallStatus = "success" | "cached" | "failed" | "timeout" | "skipped";

export interface ProviderCall {
  id: string;
  provider: string;
  operation: string;
  model_version: string | null;
  request_id: string | null;
  status: ProviderCallStatus;
  latency_ms: number | null;
  estimated_cost: number | null;
  /** SHA-256 of the request content; never the content itself. */
  request_hash: string | null;
  response_json: Record<string, unknown> | null;
  error_json: Record<string, unknown> | null;
  created_at: string;
}

export interface ProviderCallsResponse {
  calls: ProviderCall[];
  total_estimated_cost: number;
  currency: string;
}
