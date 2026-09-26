import { defineConfig } from "@playwright/test";

if (process.env.CLAUSEIQ_REALSTACK_BROWSER !== "1") {
  throw new Error("Run npm run test:e2e:real; never point this suite at an existing installation.");
}
const baseURL = "http://127.0.0.1:3101";
export default defineConfig({
  testDir: "./e2e/real-stack",
  workers: 1,
  retries: 0,
  timeout: 90_000,
  globalTimeout: 5 * 60_000,
  expect: { timeout: 15_000 },
  outputDir: "../output/playwright/real-stack/results",
  reporter: [["list"], ["html", { outputFolder: "../output/playwright/real-stack/report", open: "never" }]],
  use: {
    browserName: "chromium", baseURL,
    viewport: { width: 1280, height: 800 }, locale: "en-GB", timezoneId: "UTC",
    serviceWorkers: "block", actionTimeout: 15_000, navigationTimeout: 45_000,
    trace: "retain-on-failure", screenshot: "only-on-failure",
  },
  webServer: {
    command: "node e2e/dev-server.mjs", url: `${baseURL}/import`,
    reuseExistingServer: false, timeout: 120_000,
    env: { CLAUSEIQ_E2E: "1", CLAUSEIQ_REALSTACK_BROWSER: "1", NEXT_PUBLIC_API_URL: "http://127.0.0.1:8101", NEXT_TELEMETRY_DISABLED: "1" },
    gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
  },
});
