// Resolve the API base URL at runtime, not build time. Order:
//   1. NEXT_PUBLIC_API_URL — explicit pin (e.g. Cloudflare tunnel domain).
//      This is read at build time by Next.js since it's a NEXT_PUBLIC_ var.
//   2. window.location — same hostname as the page, port 8000. Makes the
//      app "just work" from any device on the LAN: load the frontend from
//      http://<host-ip>:3000 and the API target follows the same host.
//   3. localhost fallback for SSR / non-browser contexts.
// The previous fixed-127.0.0.1 default broke mobile access entirely: the
// browser would try to fetch from the *phone's* loopback. Auto-deriving
// from window.location is the lowest-friction fix.
const _resolveApiUrl = (): string => {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== "undefined" && window.location?.hostname) {
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
