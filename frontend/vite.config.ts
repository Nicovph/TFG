/**
 * vite.config.ts configures the React development server and API proxy.
 */

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Keep the proxy destination server-only and preserve local npm development as
// the default when Compose does not provide its internal Django service URL.
const backendProxyTarget =
  process.env.BACKEND_PROXY_TARGET ?? 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: backendProxyTarget,
        changeOrigin: false, // Preserve the browser-visible Host (localhost:5173) header so Django origin and CSRF checks remain consistent.
      },
    },
  },
})
