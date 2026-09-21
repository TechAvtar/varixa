import type { HealthResponse } from "@verixa/shared-types";
import { env } from "@/lib/env";

/** Result of probing the API. Failure is a first-class state — never fabricate status. */
export type ApiHealth = { ok: true; data: HealthResponse } | { ok: false; error: string };

export async function fetchApiHealth(): Promise<ApiHealth> {
  try {
    const res = await fetch(`${env.apiBaseUrl}/api/v1/health`, { cache: "no-store" });
    if (!res.ok) {
      return { ok: false, error: `API responded with HTTP ${res.status}` };
    }
    const data = (await res.json()) as HealthResponse;
    return { ok: true, data };
  } catch {
    return { ok: false, error: "API is unreachable" };
  }
}
