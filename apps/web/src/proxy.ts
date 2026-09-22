import type { TokenPair } from "@verixa/shared-types";
import { NextResponse, type NextRequest } from "next/server";
import { apiRequest } from "@/lib/api/client";
import {
  ACCESS_COOKIE,
  REFRESH_COOKIE,
  clearTokenCookies,
  writeTokenCookies,
} from "@/lib/auth/cookies";
import { needsRefresh } from "@/lib/auth/jwt";

/**
 * Session gatekeeper. Runs before every matched page:
 * - keeps the access token fresh by rotating the refresh token when needed
 * - sends signed-out visitors of protected routes to /login
 * - sends signed-in visitors of /login and /register to /dashboard
 */

const PROTECTED_PREFIXES = ["/dashboard", "/analyses"];
const GUEST_ONLY = new Set(["/login", "/register"]);

export default async function proxy(request: NextRequest): Promise<NextResponse> {
  const { pathname } = request.nextUrl;
  const isProtected = PROTECTED_PREFIXES.some((p) => pathname.startsWith(p));
  const isGuestOnly = GUEST_ONLY.has(pathname);

  let access = request.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;
  let rotated: TokenPair | null = null;
  let sessionDead = false;

  if (needsRefresh(access) && refresh) {
    const result = await apiRequest<TokenPair>("/auth/refresh", {
      method: "POST",
      body: { refresh_token: refresh },
    });
    if (result.ok) {
      rotated = result.data;
      access = rotated.access_token;
    } else if (result.status === 401) {
      sessionDead = true; // refresh token revoked/expired; only a re-login helps
      access = undefined;
    }
    // Any other failure (API down) leaves cookies untouched; pages surface the error.
  }

  const signedIn = Boolean(access) && !sessionDead;
  let response: NextResponse;

  if (isProtected && !signedIn) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = pathname === "/dashboard" ? "" : `?next=${encodeURIComponent(pathname)}`;
    response = NextResponse.redirect(url);
  } else if (isGuestOnly && signedIn) {
    const url = request.nextUrl.clone();
    url.pathname = "/dashboard";
    url.search = "";
    response = NextResponse.redirect(url);
  } else {
    response = NextResponse.next();
  }

  if (rotated) writeTokenCookies(response.cookies, rotated);
  if (sessionDead) clearTokenCookies(response.cookies);
  return response;
}

export const config = {
  matcher: ["/dashboard/:path*", "/analyses/:path*", "/login", "/register"],
};
