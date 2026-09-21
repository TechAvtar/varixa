/** Mirrors `app/schemas/health.py::HealthResponse`. */
export interface HealthResponse {
  status: "ok" | "degraded";
  service: string;
  version: string;
  environment: string;
  database: "ok" | "unavailable";
}
