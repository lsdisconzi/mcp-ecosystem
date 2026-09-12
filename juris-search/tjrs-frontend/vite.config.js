import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

function searchRouteFallback() {
  const rewrite = (req, _res, next) => {
    if (req.url === '/search' || req.url === '/search/') req.url = '/juris/'
    next()
  }

  return {
    name: 'search-route-fallback',
    configureServer(server) {
      server.middlewares.use(rewrite)
    },
    configurePreviewServer(server) {
      server.middlewares.use(rewrite)
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), searchRouteFallback()],
  base: '/juris/',
  appType: 'spa',
  server: {
    // The API runs on the FastAPI backend (default :8000), served both under
    // /api/... and /juris/api/.... When the SPA is loaded from this Vite dev
    // server, API_BASE resolves to the same origin, so we proxy those paths to
    // the backend. Without this the dev server returns index.html for /api/*
    // requests, which the frontend fails to parse as JSON.
    proxy: {
      '/juris/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
