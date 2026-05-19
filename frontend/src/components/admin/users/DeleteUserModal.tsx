"use client";

import { FormEvent, useState } from "react";
import { apiFetch } from "@/utils/apiClient";
import { ModalShell } from "@/components/admin/ModalShell";
import { Field } from "@/components/admin/Field";
import { Checkbox } from "./Checkbox";
import type { AdminUser } from "./types";

export function DeleteUserModal({
  target,
  onClose,
  onDone,
}: {
  target: AdminUser;
  onClose: () => void;
  onDone: () => void;
}) {
  const [hardDelete, setHardDelete] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Hard delete requires the admin to type the username — destructive
  // cascade through sessions/folders/documents, no undo.
  const canSubmit = hardDelete ? confirmText === target.username : true;

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const url = `/api/admin/users/${encodeURIComponent(target.id)}${hardDelete ? "?hard=true" : ""}`;
      const r = await apiFetch(url, { method: "DELETE" });
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
    <ModalShell title={`Delete ${target.username}`} onClose={onClose}>
      <form onSubmit={submit} className="p-5 space-y-4">
        <p className="text-sm text-gray-300">
          By default this is a <strong>soft delete</strong> — the user is
          marked inactive and signed out everywhere. Their workspaces,
          chats, and bug reports remain intact, and you can reactivate
          them later.
        </p>

        <Checkbox
          label="Hard delete (cascades through everything)"
          hint="Removes the user row AND their workspaces, chats, folders, and documents. Audit history stays (FK SET NULL on user_id)."
          checked={hardDelete}
          onChange={(v) => {
            setHardDelete(v);
            setConfirmText("");
          }}
        />

        {hardDelete && (
          <Field label={`Type "${target.username}" to confirm`}>
            <input
              type="text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm font-mono"
              autoComplete="off"
            />
          </Field>
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
            disabled={submitting || !canSubmit}
            className={
              "text-sm px-3 py-1.5 rounded border " +
              (hardDelete
                ? "bg-red-500/20 border-red-500/40 text-red-200 hover:bg-red-500/30 disabled:opacity-50"
                : "bg-amber-500/15 border-amber-500/30 text-amber-200 hover:bg-amber-500/25 disabled:opacity-50")
            }
          >
            {submitting
              ? "Deleting…"
              : hardDelete
              ? "Hard delete"
              : "Soft delete"}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}
