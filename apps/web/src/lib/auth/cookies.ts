import type { TokenPair } from "@verixa/shared-types";

/** Token cookies are httpOnly; the browser never reads them, only carries them. */
export const ACCESS_COOKIE = "verixa_access";
export const REFRESH_COOKIE = "verixa_refresh";

const REFRESH_MAX_AGE_SECONDS = 14 * 24 * 60 * 60; // mirrors VERIXA_REFRESH_TOKEN_TTL_DAYS

export interface CookieWriter {
  set(name: string, value: string, options: CookieOptions): unknown;
  delete(name: string): unknown;
}

export interface CookieOptions {
  httpOnly: boolean;
  sameSite: "lax";
  secure: boolean;
  path: string;
  maxAge: number;
}

function base(maxAge: number): CookieOptions {
  return {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge,
  };
}

export function writeTokenCookies(jar: CookieWriter, tokens: TokenPair): void {
  jar.set(ACCESS_COOKIE, tokens.access_token, base(tokens.expires_in));
  jar.set(REFRESH_COOKIE, tokens.refresh_token, base(REFRESH_MAX_AGE_SECONDS));
}

export function clearTokenCookies(jar: CookieWriter): void {
  jar.delete(ACCESS_COOKIE);
  jar.delete(REFRESH_COOKIE);
}
