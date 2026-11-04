import { defineConfig } from "@playwright/test";

const local = !process.env.CI;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  outputDir: ".playwright/results",
  use: {
    baseURL: "http://localhost:3000",
    // On a developer's machine, the browser already installed. In CI, the one Playwright fetches.
    ...(local ? { channel: "msedge" } : {}),
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  webServer: [
    {
      // RULES-ONLY needs no model, so these tests send nothing to any provider.
      command: "uv run --no-sync --directory ../backend tessera-api --fiction --port 8000",
      url: "http://127.0.0.1:8000/api/status",
      reuseExistingServer: local,
    },
    {
      // The production build in CI, where compiling each page on first use would be slow.
      command: local ? "npm run dev" : "npm run build && npm run start",
      url: "http://localhost:3000",
      reuseExistingServer: local,
      timeout: 180_000,
    },
  ],
});
