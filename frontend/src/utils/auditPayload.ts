export function payloadSummary(payload: Record<string, unknown>): string {
  if (!payload || Object.keys(payload).length === 0) return "—";
  if (payload._truncated && typeof payload._preview === "string") {
    return payload._preview;
  }
  const s = JSON.stringify(payload);
  return s.length > 140 ? s.slice(0, 140) + "…" : s;
}
