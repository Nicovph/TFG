/**
 * vitest.config.ts extends the production Vite configuration with the browser-like
 * environment required by the frontend unit and integration tests.
 */

import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config.ts'

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      include: ['src/**/*.test.{ts,tsx}'],
      setupFiles: './src/test/setup.ts',
    },
  }),
)
