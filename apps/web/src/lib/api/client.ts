import type { ApiErrorBody } from "@verixa/shared-types";
import { env } from "@/lib/env";

/**
 * Minimal typed client for the Verixa API. Server-side only: it is called from
 * server components, server actions and the proxy, never from the browser, so
 * tokens stay in httpOnly cookies.
 */

export type ApiResult<T> =
  | { ok: true; status: number; data: T }
  | { ok: false; status: number; code: string; message: string; requestId?: string };

export interface ApiRequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  token?: string | null;
}

const UNREACHABLE: ApiResult<never> = {
  ok: false,
  status: 0,
  code: "API_UNREACHABLE",
  message: "The Verixa API could not be reached.",
};

async function send<T>(path: string, init: RequestInit): Promise<ApiResult<T>> {
  let res: Response;
  try {
    res = await fetch(`${env.apiBaseUrl}/api/v1${path}`, { ...init, cache: "no-store" });
  } catch {
    return UNREACHABLE;
  }

  if (res.status === 204) return { ok: true, status: 204, data: undefined as T };

  let payload: unknown = null;
  try {
    payload = await res.json();
  } catch {
    // Non-JSON body: fall through to a generic error below.
  }

  if (res.ok) return { ok: true, status: res.status, data: payload as T };

  const err = (payload as Partial<ApiErrorBody> | null)?.error;
  return {
    ok: false,
    status: res.status,
    code: err?.code ?? "HTTP_ERROR",
    message: err?.message ?? `Request failed with HTTP ${res.status}.`,
    requestId: err?.request_id,
  };
}

export async function apiRequest<T>(
  path: string,
  { method = "GET", body, token }: ApiRequestOptions = {},
): Promise<ApiResult<T>> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  return send<T>(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

/** Multipart POST; the browser-provided FormData is forwarded as-is. */
export async function apiUpload<T>(
  path: string,
  form: FormData,
  { token }: { token?: string | null } = {},
): Promise<ApiResult<T>> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  return send<T>(path, { method: "POST", headers, body: form });
}
