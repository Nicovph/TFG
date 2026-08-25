/**
 * playwright.config.ts runs the browser suite against the isolated HTTPS stack.
 */

import process from 'node:process'
import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  // Fail the run on CI if any test.only() is left in the source.
  forbidOnly: Boolean(process.env.CI),
  // Print one line per test with pass/fail status.
  reporter: 'list',
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'https://localhost',
    browserName: 'chromium',
    // Accept Caddy's internal (self-signed) TLS certificate.
    ignoreHTTPSErrors: true,
    // Record a trace for every run; keep it only when the test fails.
    trace: 'retain-on-failure',
  },
  // Run tests sequentially to avoid shared-state races.
  workers: 1,
})
