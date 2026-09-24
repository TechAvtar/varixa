/** Mirrors `app/schemas/health.py::HealthResponse`. */
export interface HealthResponse {
  status: "ok" | "degraded";
  service: string;
  version: string;
  environment: string;
  database: "ok" | "unavailable";
  storage: "ok" | "unavailable";
  /** Configured engine/provider names only (never keys or endpoints). */
  providers: Record<string, string>;
  uptime_seconds: number;
  /** Binary engines the pipeline shells out to (c2patool): status and version, never paths. */
  engines: Record<
    string,
    {
      status: "ok" | "unavailable" | "not_configured";
      version: string | null;
      /** Trust-list mode and version the provenance engine evaluates against (c2patool). */
      trust?: { mode: string; list_version: string | null };
    }
  >;
}

/** Mirrors `app/schemas/health.py::LivenessResponse`. */
export interface LivenessResponse {
  status: "ok";
}
