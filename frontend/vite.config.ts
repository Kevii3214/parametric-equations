import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Let the dev server read ../fixtures (sample data shared with the server).
  server: { fs: { allow: ['..'] } },
})
