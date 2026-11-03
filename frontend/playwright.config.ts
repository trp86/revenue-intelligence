// The walkthrough (story #136): the real API on a synthetic warehouse, and the Vite dev server.
// `npm run e2e`. The warehouse is built into e2e/.data (git-ignored) by e2e/make_warehouse.py.
import { defineConfig } from "@playwright/test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const DATA = resolve(HERE, "e2e", ".data");
const ROOT = resolve(HERE, "..");

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  use: { baseURL: "http://localhost:5173", trace: "off" },
  webServer: [
    {
      command:
        `uv run python frontend/e2e/make_warehouse.py "${DATA}" && ` +
        "uv run revint serve",
      cwd: ROOT,
      env: {
        REVINT_PATHS_WAREHOUSE: resolve(DATA, "warehouse.duckdb"),
        REVINT_PATHS_APP_DB: resolve(DATA, "app.duckdb"),
      },
      url: "http://127.0.0.1:8000/api/v1/health",
      timeout: 300_000,
      reuseExistingServer: false,
    },
    {
      command: "npm run dev",
      url: "http://localhost:5173",
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
});
