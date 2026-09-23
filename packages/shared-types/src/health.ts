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
}

/** Mirrors `app/schemas/health.py::LivenessResponse`. */
export interface LivenessResponse {
  status: "ok";
}
