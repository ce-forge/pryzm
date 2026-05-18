import { APP_CONFIG } from "./constants";

/**
 * Wraps fetch with cross-origin credentials. The session cookie carries
 * auth; the wrapper sets no Authorization header.
 *
 * IMPORTANT: this wrapper does NOT touch Content-Type. Callers that pass a
 * FormData body MUST leave Content-Type unset so the browser sets the
 * multipart boundary automatically. Callers that send JSON must set
 * Content-Type: application/json themselves.
 *
 * For SSE/streaming responses, this returns the raw Response so callers can
 * use response.body.getReader() as before.
 */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  return fetch(`${APP_CONFIG.API_URL}${path}`, {
    ...init,
    credentials: "include",
  });
}
