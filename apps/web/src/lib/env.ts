/**
 * Public, build-time environment configuration for the web app.
 * Only NEXT_PUBLIC_* values are exposed to the browser; never put secrets here.
 */
export const env = {
  apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
} as const;
