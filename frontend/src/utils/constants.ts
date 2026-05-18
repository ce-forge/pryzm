// Resolve the API base URL. Order:
//   1. NEXT_PUBLIC_API_URL — explicit pin if set; overrides everything.
//   2. Same origin when the page is served on a default port (80/443) —
//      indicates a reverse proxy is in front.
//   3. Public hostname + NEXT_PUBLIC_API_EXTERNAL_PORT set — use that port
//      on the same hostname (covers modem port-remap setups where external
//      X forwards to internal :8000).
//   4. Same hostname on :8000 — LAN/dev where the backend is the sibling.
//   5. Localhost fallback for SSR / non-browser contexts.
const _PRIVATE_HOST_RE = /^(localhost$|127\.|10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)/;
const _resolveApiUrl = (): string => {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== "undefined" && window.location?.hostname) {
    if (!window.location.port) return window.location.origin;
    const hostname = window.location.hostname;
    const externalPort = process.env.NEXT_PUBLIC_API_EXTERNAL_PORT;
    const isPrivate = _PRIVATE_HOST_RE.test(hostname);
    const port = !isPrivate && externalPort ? externalPort : "8000";
    return `${window.location.protocol}//${hostname}:${port}`;
  }
  return "http://127.0.0.1:8000";
};

export const APP_CONFIG = {
  get API_URL(): string {
    return _resolveApiUrl();
  },
  // The model's num_ctx is 8192 (see backend/core/ai_engine.py). Out of that
  // we reserve ~2K tokens for the system prompt, tool definitions, memory
  // summary, and a sensible response budget — so the user-facing counter
  // tops out below the technical ceiling.
  VISIBLE_TOKEN_LIMIT: 6000,
};
