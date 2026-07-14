/**
 * vite.config.ts configures the React development server and API proxy.
 */

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false, // Preserve the browser-visible Host (localhost:5173) header so Django origin and CSRF checks remain consistent.
      },
    },
  },
})
