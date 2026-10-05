/**
 * Environment configuration for the web app.
 * Only NEXT_PUBLIC_* values are exposed to the browser; never put secrets here.
 *
 * `apiBaseUrl` is only used server-side (server components, actions, the proxy). In a
 * container deployment the API is reached over the private network, so the runtime-only
 * `API_BASE_URL` wins over the public origin baked in at build time.
 */
export const env = {
  // Trailing slashes are dropped because callers append "/api/v1/...". On Vercel, `API_BASE_URL`
  // is the `api` service binding (vercel.json); bindings do not exist in the proxy, which then
  // falls back to the public origin in NEXT_PUBLIC_API_BASE_URL.
  apiBaseUrl: (
    process.env.API_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "http://localhost:8000"
  ).replace(/\/+$/, ""),
} as const;
