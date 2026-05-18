"use client";

import { useState } from "react";
import { apiFetch } from "@/utils/apiClient";

const MIN_LENGTH = 4;

export default function ChangePasswordForm({
  onSuccess,
  forcedMode = false,
}: {
  onSuccess?: () => void;
  forcedMode?: boolean;
}) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(false);
    if (next.length < MIN_LENGTH) {
      setError(`New password must be at least ${MIN_LENGTH} characters.`);
      return;
    }
    if (next !== confirm) {
      setError("New passwords do not match.");
      return;
    }
    setIsSubmitting(true);
    try {
      const r = await apiFetch("/api/auth/password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      if (r.ok) {
        setSuccess(true);
        setCurrent("");
        setNext("");
        setConfirm("");
        if (onSuccess) onSuccess();
      } else {
        const body = await r.json().catch(() => ({}));
        setError(body?.detail || "Couldn't update password.");
      }
    } catch {
      setError("Network error. Try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      {forcedMode && (
        <p className="text-sm text-amber-300">
          Your account is using a default password. Please change it before continuing.
        </p>
      )}
      <div>
        <label className="block text-xs text-slate-400 mb-1">Current password</label>
        <input
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
      </div>
      <div>
        <label className="block text-xs text-slate-400 mb-1">New password</label>
        <input
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
        <p className="text-[11px] text-slate-500 mt-1">Minimum {MIN_LENGTH} characters.</p>
      </div>
      <div>
        <label className="block text-xs text-slate-400 mb-1">Confirm new password</label>
        <input
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
      </div>
      {error && <p className="text-sm text-red-400">{error}</p>}
      {success && <p className="text-sm text-emerald-400">Password updated.</p>}
      <button
        type="submit"
        disabled={isSubmitting || !current || !next || !confirm}
        className="w-full rounded bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isSubmitting ? "Updating…" : "Update password"}
      </button>
    </form>
  );
}
