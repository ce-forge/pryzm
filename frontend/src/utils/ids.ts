/**
 * Optimistic / temporary IDs used by the chat UI before a real DB UUID arrives.
 *
 * crypto.randomUUID() (rather than Date.now()) so rapid sends, double-clicks,
 * and React 19 strict-mode double invocation don't produce colliding IDs.
 */
export function newOptimisticSessionId(): string {
  return `optimistic-${crypto.randomUUID()}`;
}

export function newTempMessageId(role: "u" | "a"): string {
  return `temp-${role}-${crypto.randomUUID()}`;
}

export function isOptimisticSessionId(id: string | null | undefined): boolean {
  return !!id && id.startsWith("optimistic-");
}

export function isTempMessageId(id: string | null | undefined): boolean {
  return !!id && id.startsWith("temp-");
}
