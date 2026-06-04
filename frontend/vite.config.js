import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
const backendHost = process.env.BACKEND_HOST || 'localhost'
const backendPort = process.env.BACKEND_PORT || '8001'
const backendTarget = process.env.VITE_API_PROXY_TARGET || `http://${backendHost}:${backendPort}`

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.js',
    globals: true,
  },
  build: {
    chunkSizeWarningLimit: 700,
  },
  server: {
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
})
