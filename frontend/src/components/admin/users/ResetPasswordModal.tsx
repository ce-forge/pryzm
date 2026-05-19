"use client";

import { FormEvent, useState } from "react";
import { apiFetch } from "@/utils/apiClient";
import { ModalShell } from "@/components/admin/ModalShell";
import { Field } from "@/components/admin/Field";
import type { AdminUser } from "./types";
import { PASSWORD_MIN } from "./types";

export function ResetPasswordModal({
  target,
  onClose,
  onDone,
}: {
  target: AdminUser;
  onClose: () => void;
  onDone: () => void;
}) {
  const [newPassword, setNewPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (newPassword.length < PASSWORD_MIN) {
      setError(`Password must be at least ${PASSWORD_MIN} characters.`);
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const r = await apiFetch(
        `/api/admin/users/${encodeURIComponent(target.id)}/password`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ new_password: newPassword }),
        },
      );
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
      onDone();
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ModalShell
      title={`Reset password for ${target.username}`}
      onClose={onClose}
      size="max-w-sm"
    >
      <form onSubmit={submit} className="p-5 space-y-4">
        <p className="text-xs text-gray-400">
          The user will be forced to pick a new password on their next
          login, and all of their existing sessions will be signed out.
        </p>

        <Field label={`New password (min ${PASSWORD_MIN} chars)`}>
          <input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            autoComplete="new-password"
            className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm"
            autoFocus
          />
        </Field>

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
            disabled={submitting}
            className="text-sm px-3 py-1.5 rounded bg-[#2a2a2c] hover:bg-[#3a3a3c] disabled:opacity-50"
          >
            {submitting ? "Resetting…" : "Reset password"}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}
