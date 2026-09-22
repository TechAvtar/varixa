import { defineConfig, devices } from "@playwright/test";
import os from "node:os";
import path from "node:path";

/**
 * End-to-end tests (docs/10): a real API (SQLite + local storage in a scratch directory, mock
 * providers, no network) and a real Next.js server, both started here on their own ports so they
 * never touch the developer's running servers or data. Set E2E_WEB_URL / E2E_API_URL to run the
 * specs against servers you started yourself.
 */
const API_PORT = 8100;
const WEB_PORT = 3100;
const apiUrl = process.env.E2E_API_URL ?? `http://127.0.0.1:${API_PORT}`;
const webUrl = process.env.E2E_WEB_URL ?? `http://127.0.0.1:${WEB_PORT}`;
const apiDir = path.resolve(__dirname, "../../services/api");
const dataDir = path.join(os.tmpdir(), "verixa-e2e");
const python =
  process.env.E2E_PYTHON ??
  (process.platform === "win32" ? ".venv\\Scripts\\python.exe" : ".venv/bin/python");

const apiEnv = {
  VERIXA_ENVIRONMENT: "test",
  VERIXA_DATA_DIR: dataDir,
  VERIXA_CORS_ORIGINS: JSON.stringify([webUrl]),
  VERIXA_API_PUBLIC_URL: apiUrl,
  VERIXA_AI_DETECTOR_PROVIDER: "mock",
  VERIXA_SOURCE_SEARCH_PROVIDER: "mock",
  VERIXA_LLM_PROVIDER: "mock",
  VERIXA_RETENTION_SWEEP_INTERVAL_MINUTES: "0",
  VERIXA_LOGIN_MAX_ATTEMPTS: "0", // specs sign in many times from one address
  VERIXA_REGISTER_MAX_PER_HOUR: "0",
};

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // One worker: the API is a single process whose pipeline steps are CPU-bound, so parallel
  // specs would time each other out rather than find real bugs.
  workers: 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  timeout: 90_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: webUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // Fresh scratch data directory, migrated, then the API with mock providers only.
      command: [
        `${python} -c "import os,shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True); os.makedirs(sys.argv[1])" "${dataDir}"`,
        `${python} -m alembic upgrade head`,
        `${python} -m uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT} --log-level warning`,
      ].join(" && "),
      cwd: apiDir,
      url: `${apiUrl}/api/v1/health`,
      env: apiEnv,
      reuseExistingServer: !!process.env.E2E_API_URL,
      timeout: 120_000,
    },
    {
      // A production build in its own dist dir: no HMR noise, no clash with a running `next dev`.
      command: `npx next build && npx next start --port ${WEB_PORT}`,
      cwd: __dirname,
      url: webUrl,
      env: {
        NEXT_PUBLIC_API_BASE_URL: apiUrl,
        NEXT_DIST_DIR: ".next-e2e",
        NEXT_TELEMETRY_DISABLED: "1",
      },
      reuseExistingServer: !!process.env.E2E_WEB_URL,
      timeout: 300_000,
    },
  ],
});
