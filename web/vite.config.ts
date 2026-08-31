import path from 'node:path'
import { fileURLToPath } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const here = path.dirname(fileURLToPath(import.meta.url))

// In development the pages come from Vite and the data from the FastAPI process
// next door, so /api is proxied rather than fetched cross-origin. In production
// that same FastAPI process serves this build and the proxy is not involved.
const API = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(here, './src') },
  },
  server: {
    proxy: {
      '/api': { target: API, changeOrigin: true },
    },
  },
})
