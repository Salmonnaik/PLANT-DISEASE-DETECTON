import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

/**
 * Vite configuration.
 *
 * In development the dashboard runs on :5173 and the Flask API on :5000. Rather
 * than baking an absolute API URL into the bundle (which would break CORS and
 * every time the backend host changes), `/api` and `/uploads` are proxied to the
 * backend. That way all frontend code can use same-origin relative paths.
 *
 * `host: true` binds to every interface so the dashboard can be opened from a
 * phone or another laptop on the same Wi-Fi during a demo.
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const backendTarget = env.VITE_BACKEND_URL || 'http://127.0.0.1:5000';

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      port: 5173,
      host: true,
      strictPort: false,
      proxy: {
        '/api': {
          target: backendTarget,
          changeOrigin: true,
          // A capture can legitimately take ~30s while the firmware is polled,
          // so the proxy must not time out before the backend gives up.
          timeout: 120000,
          proxyTimeout: 120000,
        },
        '/uploads': {
          target: backendTarget,
          changeOrigin: true,
        },
      },
    },
    preview: {
      port: 4173,
      host: true,
      proxy: {
        '/api': { target: backendTarget, changeOrigin: true },
        '/uploads': { target: backendTarget, changeOrigin: true },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
      chunkSizeWarningLimit: 900,
      rollupOptions: {
        output: {
          manualChunks: {
            react: ['react', 'react-dom', 'react-router-dom'],
            charts: ['recharts'],
          },
        },
      },
    },
  };
});
