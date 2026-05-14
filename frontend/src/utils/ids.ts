/**
 * Optimistic / temporary IDs used by the chat UI before a real DB UUID arrives.
 *
 * crypto.randomUUID() (rather than Date.now()) so rapid sends, double-clicks,
 * and React 19 strict-mode double invocation don't produce colliding IDs.
 *
 * `crypto.randomUUID` requires a SECURE CONTEXT — HTTPS or localhost. On HTTP
 * over LAN (Samsung Internet PWA on http://192.168.x.x:3000, for example) the
 * API isn't available and the bare call throws "TypeError: crypto.randomUUID
 * is not a function". `safeRandomUUID` falls back to a Math.random-derived
 * v4-shaped UUID for that case. These IDs are short-lived UI temps that get
 * replaced by the real DB UUID at stream start, so the cryptographic
 * weakness of Math.random isn't load-bearing.
 */
function safeRandomUUID(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // RFC 4122 v4 shape: positions 14 and 19 (the variant nibble) get the
  // right high bits because of the precedence c ^ ((rand << 4) >> (c/4)) —
  // for c="8", the shift narrows random to 0..3, OR'd against 8 → 8..b.
  return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) => {
    const n = Number(c);
    return (n ^ ((Math.random() * 16) >> (n / 4))).toString(16);
  });
}

export function newOptimisticSessionId(): string {
  return `optimistic-${safeRandomUUID()}`;
}

export function newTempMessageId(role: "u" | "a"): string {
  return `temp-${role}-${safeRandomUUID()}`;
}

export function isOptimisticSessionId(id: string | null | undefined): boolean {
  return !!id && id.startsWith("optimistic-");
}

export function isTempMessageId(id: string | null | undefined): boolean {
  return !!id && id.startsWith("temp-");
}
