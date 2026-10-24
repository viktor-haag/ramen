import { defineConfig } from "@playwright/test";

// Every test gets its own backend with a fresh temporary data dir (see tests/e2e/fixtures.ts),
// so there is no shared DB state between tests. globalSetup builds the frontend once.
export default defineConfig({
  testDir: "tests/e2e",
  testMatch: /.*\.spec\.ts/,
  globalSetup: "./tests/e2e/global-setup.ts",
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    trace: "retain-on-failure",
    // Optional: use a preinstalled Chromium instead of the one `playwright install` fetches.
    launchOptions: { executablePath: process.env.PW_CHROMIUM || undefined },
  },
});
