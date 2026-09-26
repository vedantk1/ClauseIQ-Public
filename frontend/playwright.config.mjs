import { defineConfig } from "@playwright/test";

// Deliberately fixed and separate from the person's running local installation.
const baseURL = "http://127.0.0.1:3100";

export default defineConfig({
  testDir: "./e2e",
  testIgnore: "**/real-stack/**",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  globalTimeout: 5 * 60_000,
  expect: { timeout: 10_000 },
  outputDir: "../output/playwright/results",
  reporter: [["list"], ["html", { outputFolder: "../output/playwright/report", open: "never" }]],
  use: {
    browserName: "chromium",
    baseURL,
    viewport: { width: 1280, height: 800 },
    locale: "en-GB",
    timezoneId: "UTC",
    serviceWorkers: "block",
    actionTimeout: 10_000,
    navigationTimeout: 30_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "node e2e/dev-server.mjs",
    url: `${baseURL}/import`,
    reuseExistingServer: false,
    timeout: 90_000,
    env: { CLAUSEIQ_E2E: "1", NEXT_PUBLIC_API_URL: baseURL, NEXT_TELEMETRY_DISABLED: "1" },
    gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
  },
});
