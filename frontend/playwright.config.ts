import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against a running stack: the Vite dev server by default, or the Docker
 * Compose stack in CI (E2E_BASE_URL=http://localhost:8080). They sign in with the demo
 * accounts from .env, so they only ever touch a local, synthetic deployment.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  // The tests share one database and some change simulation state: run them in order.
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        // Always render WebGL with SwiftShader (CPU), as on GPU-less CI runners, so runs are
        // comparable everywhere. The twin detects the software renderer and reduces effects.
        launchOptions: { args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] },
      },
    },
  ],
});
