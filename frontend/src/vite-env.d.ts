/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * Absolute backend URL for the built bundle, e.g. `http://192.168.1.10:5000`.
   * Leave unset in development: requests stay same-origin and the Vite dev
   * server proxies `/api` and `/uploads` to Flask.
   */
  readonly VITE_API_BASE_URL?: string;
  /** Proxy target used by vite.config.ts during `npm run dev`. */
  readonly VITE_BACKEND_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
