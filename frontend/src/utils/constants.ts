// Resolve the API base URL. Order:
//   1. NEXT_PUBLIC_API_URL — explicit pin if set.
//   2. Same origin when the page is served on a default port (80 or 443) —
//      indicates a reverse proxy is in front, routing /api/* and the backend
//      routes to the backend on its private port.
//   3. Same hostname on :8000 — direct dev/LAN access where the frontend is
//      served on :3000 and the backend lives on :8000 alongside it.
//   4. Localhost fallback for SSR / non-browser contexts.
const _resolveApiUrl = (): string => {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== "undefined" && window.location?.hostname) {
    if (!window.location.port) return window.location.origin;
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return "http://127.0.0.1:8000";
};

export const APP_CONFIG = {
  get API_URL(): string {
    return _resolveApiUrl();
  },
  DEFAULT_WORKSPACE: "it_copilot",
  // The model's num_ctx is 8192 (see backend/core/ai_engine.py). Out of that
  // we reserve ~2K tokens for the system prompt, tool definitions, memory
  // summary, and a sensible response budget — so the user-facing counter
  // tops out below the technical ceiling.
  VISIBLE_TOKEN_LIMIT: 6000,
};
