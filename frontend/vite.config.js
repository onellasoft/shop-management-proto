import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');

  // Where the dev-server proxy forwards /api requests. In Docker this is the
  // backend service URL; locally it defaults to the backend on localhost:8000.
  const apiTarget = env.VITE_API_PROXY_TARGET || 'http://localhost:8000';

  return {
    plugins: [react()],
    server: {
      host: true, // bind 0.0.0.0 so the container is reachable from the host
      port: 4300,
      open: false,
      // Forward /api/* to the backend, stripping the /api prefix so it maps
      // onto the backend's root-level routes (/health, /auth, ...). The app
      // code calls fetch(`${VITE_API_URL}/...`) with VITE_API_URL="/api".
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
  };
});
