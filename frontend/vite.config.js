import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API remains local-only. In development, Vite forwards relative /api
// requests to the FastAPI process so the client code also works when built.
export default defineConfig({
  plugins: [react()],
  // Relative asset URLs so the built site works under any sub-path
  // (GitHub Pages project sites, Netlify/Vercel previews, custom domains).
  // The API base is injected at build time via VITE_API_BASE_URL.
  base: './',
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
