import { APP_CONFIG } from "./constants";

const TOKEN_STORAGE_KEY = "pryzm_api_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}

/**
 * Wraps fetch with the Authorization header. Pass a path starting with `/`
 * (e.g. "/sessions"); the wrapper prepends APP_CONFIG.API_URL.
 *
 * IMPORTANT: this wrapper does NOT touch Content-Type. Callers that pass a
 * FormData body MUST leave Content-Type unset so the browser sets the
 * multipart boundary automatically. Callers that send JSON must set
 * Content-Type: application/json themselves (existing behavior).
 *
 * For SSE/streaming responses, this returns the raw Response so callers can
 * use response.body.getReader() as before.
 */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(`${APP_CONFIG.API_URL}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
}
