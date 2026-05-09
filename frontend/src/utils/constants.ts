export const APP_CONFIG = {
  // Respects .env.local, fallbacks to localhost
  API_URL: process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000",
  DEFAULT_MODEL: "gemma4:e4b",
  DEFAULT_WORKSPACE: "it_copilot",
  MAX_TOKENS: 8192
};