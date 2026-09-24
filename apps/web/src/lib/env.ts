/**
 * Environment configuration for the web app.
 * Only NEXT_PUBLIC_* values are exposed to the browser; never put secrets here.
 *
 * `apiBaseUrl` is only used server-side (server components, actions, the proxy). In a
 * container deployment the API is reached over the private network, so the runtime-only
 * `API_BASE_URL` wins over the public origin baked in at build time.
 */
export const env = {
  apiBaseUrl:
    process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
} as const;
