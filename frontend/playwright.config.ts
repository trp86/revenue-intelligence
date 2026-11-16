// The walkthrough (stories #136, #138): the real API on a synthetic warehouse with a fake
// Gemini (e2e/serve_fake_ai.py), and the Vite dev server.
// `npm run e2e`. The warehouse is built into e2e/.data (git-ignored) by e2e/make_warehouse.py.
import { defineConfig } from "@playwright/test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const DATA = resolve(HERE, "e2e", ".data");
const ROOT = resolve(HERE, "..");
// own ports, so a `revint serve` or `npm run dev` the user has open is left alone
const API_PORT = 8765;
const WEB_PORT = 5174;

export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  // the tests share one server and one generated brief, so they run one at a time, in order
  workers: 1,
  fullyParallel: false,
  use: { baseURL: `http://localhost:${WEB_PORT}`, trace: "off" },
  webServer: [
    {
      command:
        `uv run python frontend/e2e/make_warehouse.py "${DATA}" && ` +
        "uv run python frontend/e2e/serve_fake_ai.py",
      cwd: ROOT,
      env: {
        REVINT_PATHS_WAREHOUSE: resolve(DATA, "warehouse.duckdb"),
        REVINT_PATHS_APP_DB: resolve(DATA, "app.duckdb"),
        REVINT_PATHS_USERS: resolve(DATA, "users.json"), // a test-only user (story #191)
        REVINT_E2E_PORT: String(API_PORT),
        REVINT_E2E_ORIGIN: `http://localhost:${WEB_PORT}`,
      },
      url: `http://127.0.0.1:${API_PORT}/api/v1/health`,
      timeout: 300_000,
      reuseExistingServer: false,
    },
    {
      command: `npx vite --port ${WEB_PORT} --strictPort`,
      // localhost, like the page, so the browser sends the session cookie (same site, story #191)
      env: { VITE_API_BASE: `http://localhost:${API_PORT}/api/v1` },
      url: `http://localhost:${WEB_PORT}`,
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
});
