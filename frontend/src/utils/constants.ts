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
  MAX_TOKENS: 8192
};