/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Origin the SPA prepends to /api/... requests. Empty means same-origin. */
  readonly VITE_API_BASE_URL?: string
  /** "1" renders bundled fixtures for demo- ids in a production build too. */
  readonly VITE_USE_FIXTURES?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
