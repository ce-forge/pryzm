"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/utils/apiClient";
import { ModalShell } from "./ModalShell";
import type { AdminTemplate } from "./types";

export function TemplatePushModal({
  target,
  onClose,
  onDone,
}: {
  target: AdminTemplate;
  onClose: () => void;
  onDone: () => void;
}) {
  const [affectedCount, setAffectedCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [filtered, setFiltered] = useState<
    { user_id: string | null; username: string | null; dropped_tools: string[] }[]
  >([]);

  useEffect(() => {
    let cancelled = false;
    apiFetch(`/api/admin/workspaces?template_id=${encodeURIComponent(target.id)}`)
      .then(async (r) => {
        if (cancelled) return;
        if (!r.ok) {
          setError(`Failed to count instances (${r.status})`);
          return;
        }
        const body = await r.json();
        setAffectedCount(Array.isArray(body) ? body.length : 0);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [target.id]);

  const confirm = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const r = await apiFetch(
        `/api/admin/templates/${encodeURIComponent(target.id)}/push`,
        { method: "POST" },
      );
      if (!r.ok) {
        setError(`Push failed (${r.status})`);
        return;
      }
      const body = await r.json();
      const f = Array.isArray(body.filtered) ? body.filtered : [];
      setFiltered(f);
      setDone(true);
      if (f.length === 0) {
        setTimeout(onDone, 900);
      }
      // else: stay open — admin reads the filtered list and clicks Close
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ModalShell title={`Push ${target.slug}`} onClose={onClose}>
      <div className="p-5 space-y-4 text-sm">
        {loading ? (
          <div className="text-gray-400">Counting instances…</div>
        ) : done ? (
          <div className="space-y-3">
            <div className="text-emerald-300">Push complete.</div>
            {filtered.length > 0 && (
              <div className="text-xs text-gray-300 space-y-1">
                <div>
                  Filtered tools for {filtered.length} user
                  {filtered.length === 1 ? "" : "s"} due to per-user restrictions:
                </div>
                <ul className="list-disc pl-5 space-y-0.5">
                  {filtered.map((f) => (
                    <li key={f.user_id ?? f.username ?? ""}>
                      <span className="font-mono text-[#e3e3e3]">
                        {f.username ?? "(unknown)"}
                      </span>{" "}
                      — dropped{" "}
                      <code className="font-mono text-amber-300">
                        {f.dropped_tools.join(", ")}
                      </code>
                    </li>
                  ))}
                </ul>
                <button
                  type="button"
                  onClick={onDone}
                  className="text-sm px-3 py-1.5 rounded bg-[#1e1e1f] border border-[#2a2a2c] hover:bg-[#2a2a2c] mt-2"
                >
                  Close
                </button>
              </div>
            )}
          </div>
        ) : (
          <>
            <p className="text-gray-300">
              This will overwrite the system prompt, enabled tools, color, and
              engine config on{" "}
              <strong>
                {affectedCount} workspace{affectedCount === 1 ? "" : "s"}
              </strong>{" "}
              instantiated from this template. Per-workspace customizations
              that diverge from the template will be lost.
            </p>
            {error && <div className="text-red-400">{error}</div>}
            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={onClose}
                className="text-sm px-3 py-1.5 rounded bg-[#1e1e1f] border border-[#2a2a2c] hover:bg-[#2a2a2c]"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirm}
                disabled={submitting || affectedCount === 0}
                className="text-sm px-3 py-1.5 rounded bg-sky-500/20 border border-sky-500/40 text-sky-200 hover:bg-sky-500/30 disabled:opacity-50"
              >
                {submitting
                  ? "Pushing…"
                  : affectedCount === 0
                  ? "No instances to push"
                  : `Push to ${affectedCount}`}
              </button>
            </div>
          </>
        )}
      </div>
    </ModalShell>
  );
}
