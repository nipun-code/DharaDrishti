/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Optional absolute API origin. Empty = same origin (dev server proxies to the backend). */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
