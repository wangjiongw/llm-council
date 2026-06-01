import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
const backendHost = process.env.BACKEND_HOST || 'localhost'
const backendPort = process.env.BACKEND_PORT || '8001'
const backendTarget = process.env.VITE_API_PROXY_TARGET || `http://${backendHost}:${backendPort}`

export default defineConfig({
  plugins: [react()],
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
