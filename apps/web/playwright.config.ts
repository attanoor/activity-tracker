import { defineConfig } from "@playwright/test";

/** Runs against the live local stack (scripts\dev-up.ps1). Global setup resets the E2E accounts and their day. */
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 300_000, // the report is written by the real local model
  expect: { timeout: 15_000 },
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3030", trace: "retain-on-failure" },
});
