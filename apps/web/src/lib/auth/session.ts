import "server-only";

import type { UserResponse } from "@verixa/shared-types";
import { cookies } from "next/headers";
import { apiRequest, type ApiResult } from "@/lib/api/client";
import { ACCESS_COOKIE } from "@/lib/auth/cookies";

export async function getAccessToken(): Promise<string | null> {
  return (await cookies()).get(ACCESS_COOKIE)?.value ?? null;
}

/** Authenticated request from a server component or action. */
export async function authedRequest<T>(
  path: string,
  init?: Omit<Parameters<typeof apiRequest>[1], "token">,
): Promise<ApiResult<T>> {
  return apiRequest<T>(path, { ...init, token: await getAccessToken() });
}

export type SessionState =
  | { kind: "signed_in"; user: UserResponse }
  | { kind: "signed_out" }
  /** The API could not confirm the session (down, timeout, 5xx). Not a sign-out. */
  | { kind: "unavailable"; message: string };

/** Resolves the current session without ever throwing. */
export async function getSession(): Promise<SessionState> {
  const token = await getAccessToken();
  if (!token) return { kind: "signed_out" };
  const result = await apiRequest<UserResponse>("/auth/me", { token });
  if (result.ok) return { kind: "signed_in", user: result.data };
  if (result.status === 401) return { kind: "signed_out" };
  return { kind: "unavailable", message: result.message };
}

/** Current user, or null when not signed in or unknown. Never throws. */
export async function getCurrentUser(): Promise<UserResponse | null> {
  const session = await getSession();
  return session.kind === "signed_in" ? session.user : null;
}
