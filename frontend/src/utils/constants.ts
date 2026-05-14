export const APP_CONFIG = {
  // For LAN/mobile access, set NEXT_PUBLIC_API_URL=http://<host-lan-ip>:8000
  // in frontend/.env.local; otherwise defaults to localhost. (No automatic
  // LAN-IP override — that produced surprises when the host's IP changed.)
  API_URL: process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000",
  DEFAULT_WORKSPACE: "it_copilot",
  // The model's num_ctx is 8192 (see backend/core/ai_engine.py). Out of that
  // we reserve ~2K tokens for the system prompt, tool definitions, memory
  // summary, and a sensible response budget — so the user-facing counter
  // tops out below the technical ceiling.
  VISIBLE_TOKEN_LIMIT: 6000,
};
