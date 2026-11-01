import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const backend = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    // In development the dashboard talks to FastAPI through this proxy, so the
    // browser sees a single origin (as it will in production).
    proxy: {
      '/api': backend,
      '/ws': { target: backend.replace('http', 'ws'), ws: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
})
