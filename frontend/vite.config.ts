import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The FastAPI server that /api forwards to in dev (vercel.json does the same
// in production). Point API_PROXY_TARGET at http://localhost:8000 to use a
// local server.
const apiTarget = process.env.API_PROXY_TARGET ?? 'https://beeline-api-cbjp.onrender.com'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Let the dev server read ../fixtures (sample data shared with the server).
    fs: { allow: ['..'] },
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, '') },
    },
  },
})
