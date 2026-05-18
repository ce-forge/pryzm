"use client";

import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "@/utils/apiClient";

interface Props {
  workspaceId?: string | null;
  sessionId?: string | null;
  onClose: () => void;
}

const CATEGORIES: { value: string; label: string }[] = [
  { value: "incorrect_info", label: "Incorrect information" },
  { value: "vision_wrong", label: "Image analysis wrong" },
  { value: "tool_error", label: "Tool didn’t work" },
  { value: "slow", label: "Slow response" },
  { value: "ui_bug", label: "UI bug" },
  { value: "other", label: "Other" },
];

export function BugReportModal({ workspaceId, sessionId, onClose }: Props) {
  const [category, setCategory] = useState("");
  const [message, setMessage] = useState("");
  const [includeSession, setIncludeSession] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const canSubmit = category && message.trim().length > 0 && !submitting;

  const onSubmit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      // The endpoint reads `?workspace_id=` + `?session_id=` from query
      // params; only attach them when present so submissions from
      // dashboard pages (no workspace context) still land cleanly.
      const params = new URLSearchParams();
      if (workspaceId) params.set("workspace_id", workspaceId);
      if (sessionId && includeSession) params.set("session_id", sessionId);

      const r = await apiFetch(
        `/api/bug-reports${params.toString() ? "?" + params.toString() : ""}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            category,
            message,
            include_session: includeSession,
          }),
        },
      );
      if (!r.ok) {
        setError(`Submission failed (${r.status})`);
        return;
      }
      setSuccess(true);
      // Auto-close briefly after the success state so the user sees
      // confirmation without having to click again.
      setTimeout(onClose, 1100);
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="bg-[#1e1e1f] text-[#e3e3e3] rounded-lg w-full max-w-md border border-[#2a2a2c]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-[#2a2a2c]">
          <h3 className="text-sm font-semibold">Report a bug</h3>
          <button
            type="button"
            className="text-gray-400 hover:text-[#e3e3e3] text-lg leading-none"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {success ? (
          <div className="p-8 text-center text-sm text-emerald-300">
            Thanks — we&apos;ll look into it.
          </div>
        ) : (
          <form onSubmit={onSubmit} className="p-5 space-y-4">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-gray-400">Category</span>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm"
                required
              >
                <option value="">Pick a category…</option>
                {CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-xs text-gray-400">What went wrong?</span>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={5}
                className="bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm resize-y"
                placeholder="Describe what you saw, what you expected, and any steps that reliably reproduce it."
                required
              />
            </label>

            {sessionId && (
              <label className="flex items-start gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={includeSession}
                  onChange={(e) => setIncludeSession(e.target.checked)}
                  className="mt-1"
                />
                <span className="text-sm flex flex-col">
                  <span>Include current chat session</span>
                  <span className="text-xs text-gray-500">
                    Lets the admin read the conversation you were in when
                    you submitted this. Uncheck if the bug isn&apos;t about
                    the current chat.
                  </span>
                </span>
              </label>
            )}

            {error && <div className="text-sm text-red-400">{error}</div>}

            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={onClose}
                className="text-sm px-3 py-1.5 rounded bg-[#1e1e1f] border border-[#2a2a2c] hover:bg-[#2a2a2c]"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!canSubmit}
                className="text-sm px-3 py-1.5 rounded bg-[#2a2a2c] hover:bg-[#3a3a3c] disabled:opacity-50"
              >
                {submitting ? "Sending…" : "Submit"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
