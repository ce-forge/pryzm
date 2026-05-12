const getBaseUrl = () => {
  if (typeof window === 'undefined') {
    return process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
  }

  const isLocal = 
    window.location.hostname === 'localhost' || 
    window.location.hostname === '127.0.0.1' ||
    window.location.hostname.startsWith('192.168.');

  return isLocal 
    ? "http://192.168.0.108:8000" 
    : (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000");
};

export const APP_CONFIG = {
  API_URL: getBaseUrl(),
  DEFAULT_MODEL: "gemma4:e4b",
  DEFAULT_WORKSPACE: "it_copilot",
  // The model's num_ctx is 8192 (see backend/core/ai_engine.py). Out of that
  // we reserve ~2K tokens for the system prompt, tool definitions, memory
  // summary, and a sensible response budget — so the user-facing counter
  // tops out below the technical ceiling.
  VISIBLE_TOKEN_LIMIT: 6000,
};