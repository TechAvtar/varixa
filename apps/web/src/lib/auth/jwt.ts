/**
 * Reads the expiry of an access token WITHOUT verifying it. The web app only
 * uses this to decide when to refresh; the API remains the sole verifier.
 */
export function accessTokenExpiresAt(token: string): number | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const json = Buffer.from(parts[1].replace(/-/g, "+").replace(/_/g, "/"), "base64").toString(
      "utf8",
    );
    const exp = (JSON.parse(json) as { exp?: unknown }).exp;
    return typeof exp === "number" ? exp * 1000 : null;
  } catch {
    return null;
  }
}

/** True when the token is missing, unparseable, or expires within `skewMs`. */
export function needsRefresh(token: string | undefined, skewMs = 60_000): boolean {
  if (!token) return true;
  const exp = accessTokenExpiresAt(token);
  return exp === null || exp - Date.now() < skewMs;
}
