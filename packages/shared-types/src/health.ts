/** Mirrors `app/schemas/health.py::HealthResponse`. */
export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
  environment: string;
}
