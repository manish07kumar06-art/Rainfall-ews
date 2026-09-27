import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/replay": "http://127.0.0.1:8000",
      "/live": "http://127.0.0.1:8000",
      "/impact": "http://127.0.0.1:8000",
      "/metrics": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
})
