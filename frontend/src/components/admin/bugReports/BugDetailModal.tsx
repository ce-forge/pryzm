"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/utils/apiClient";
import Identicon from "@/components/Identicon";
import { StatusBadge } from "@/components/admin/StatusBadge";

export interface AdminBugReport {
  id: string;
  user_id: string | null;
  user_display_name: string;
  workspace_id: string | null;
  session_id: string | null;
  category: string;
  message: string;
  payload: Record<string, unknown>;
  status: string;
  resolved_at: string | null;
  resolved_by: string | null;
  created_at: string | null;
}

export const CATEGORY_LABELS: Record<string, string> = {
  incorrect_info: "Incorrect info",
  vision_wrong: "Vision wrong",
  tool_error: "Tool error",
  slow: "Slow",
  ui_bug: "UI bug",
  feedback_negative: "👎 Negative feedback",
  other: "Other",
};

interface Props {
  bug: AdminBugReport;
  onClose: () => void;
  onChanged: () => void;
}

export function BugDetailModal({ bug, onClose, onChanged }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const callAction = async (action: "acknowledge" | "resolve" | "dismiss") => {
    setBusy(true);
    setError(null);
    try {
      const r = await apiFetch(`/api/admin/bug-reports/${bug.id}/${action}`, {
        method: "POST",
      });
      if (!r.ok) {
        let detail = `Failed (${r.status})`;
        try {
          const body = await r.json();
          if (typeof body?.detail === "string") detail = body.detail;
        } catch {
          // body wasn't JSON
        }
        setError(detail);
        return;
      }
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const deleteRow = async () => {
    if (!window.confirm("Delete this alert? Cannot be undone.")) return;
    setBusy(true);
    setError(null);
    try {
      const r = await apiFetch(`/api/admin/bug-reports/${bug.id}`, {
        method: "DELETE",
      });
      if (!r.ok) {
        setError(`Delete failed (${r.status})`);
        return;
      }
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="bg-[#1e1e1f] text-[#e3e3e3] rounded-lg w-full max-w-2xl max-h-[80vh] overflow-hidden flex flex-col border border-[#2a2a2c]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-[#2a2a2c]">
          <div className="flex items-center gap-3">
            <h3 className="text-sm font-semibold">Alert</h3>
            <StatusBadge status={bug.status} />
          </div>
          <button
            type="button"
            className="text-gray-400 hover:text-[#e3e3e3] text-lg leading-none"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="overflow-y-auto custom-scrollbar p-5 space-y-4 text-sm">
          <DetailRow
            label="Category"
            value={CATEGORY_LABELS[bug.category] ?? bug.category}
          />
          <div className="flex gap-4">
            <div className="text-xs text-gray-400 w-24 shrink-0 pt-0.5">
              Reporter
            </div>
            <div className="flex-1 inline-flex items-center gap-2">
              <Identicon seed={bug.user_display_name} size={20} />
              {bug.user_display_name}
            </div>
          </div>
          <div className="flex gap-4">
            <div className="text-xs text-gray-400 w-24 shrink-0 pt-0.5">When</div>
            <div className="flex-1">
              {bug.created_at ? (
                <>
                  <div>{new Date(bug.created_at).toLocaleDateString()}</div>
                  <div>{new Date(bug.created_at).toLocaleTimeString()}</div>
                </>
              ) : (
                "—"
              )}
            </div>
          </div>
          <DetailRow label="Workspace" value={bug.workspace_id ?? "—"} mono />
          <div className="flex gap-4">
            <div className="text-xs text-gray-400 w-24 shrink-0 pt-0.5">
              Session
            </div>
            <div className="flex-1 font-mono text-xs">
              {bug.session_id ? (
                <Link
                  href={`/admin/sessions/${encodeURIComponent(bug.session_id)}`}
                  className="text-sky-400 hover:underline"
                >
                  Read session →
                </Link>
              ) : (
                "—"
              )}
            </div>
          </div>
          {bug.resolved_at && (
            <DetailRow
              label="Resolved"
              value={new Date(bug.resolved_at).toLocaleString()}
            />
          )}

          <div>
            <div className="text-xs text-gray-400 mb-1">Message</div>
            <div className="bg-[#131314] border border-[#2a2a2c] rounded p-3 text-sm whitespace-pre-wrap">
              {bug.message}
            </div>
          </div>

          {bug.payload && Object.keys(bug.payload).length > 0 && (
            <div>
              <div className="text-xs text-gray-400 mb-1">Context</div>
              <pre className="bg-[#131314] border border-[#2a2a2c] rounded p-3 text-xs overflow-x-auto custom-scrollbar">
                {JSON.stringify(bug.payload, null, 2)}
              </pre>
            </div>
          )}

          {error && <div className="text-sm text-red-400">{error}</div>}
        </div>

        <div className="flex gap-2 px-5 py-3 border-t border-[#2a2a2c] justify-end flex-wrap">
          <button
            type="button"
            onClick={deleteRow}
            disabled={busy}
            className="text-sm px-3 py-1.5 rounded bg-red-500/15 border border-red-500/30 text-red-300 hover:bg-red-500/25 disabled:opacity-50"
          >
            Delete
          </button>
          <button
            type="button"
            onClick={() => callAction("dismiss")}
            disabled={busy || bug.status === "dismissed"}
            className="text-sm px-3 py-1.5 rounded bg-[#1e1e1f] border border-[#2a2a2c] hover:bg-[#2a2a2c] disabled:opacity-50"
          >
            Dismiss
          </button>
          <button
            type="button"
            onClick={() => callAction("acknowledge")}
            disabled={busy || bug.status === "acknowledged" || bug.status === "resolved"}
            className="text-sm px-3 py-1.5 rounded bg-sky-500/15 border border-sky-500/30 text-sky-300 hover:bg-sky-500/25 disabled:opacity-50"
          >
            Acknowledge
          </button>
          <button
            type="button"
            onClick={() => callAction("resolve")}
            disabled={busy || bug.status === "resolved"}
            className="text-sm px-3 py-1.5 rounded bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/25 disabled:opacity-50"
          >
            Resolve + notify
          </button>
        </div>
      </div>
    </div>
  );
}

function DetailRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex gap-4">
      <div className="text-xs text-gray-400 w-24 shrink-0 pt-0.5">{label}</div>
      <div className={(mono ? "font-mono text-xs " : "") + "flex-1"}>
        {value}
      </div>
    </div>
  );
}
