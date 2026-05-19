"use client";

import { FormEvent, useState } from "react";
import { apiFetch } from "@/utils/apiClient";
import { ModalShell } from "@/components/admin/ModalShell";
import { Field } from "@/components/admin/Field";
import type { AdminTemplate, AdminUserRow } from "./types";

export function TemplateInstantiateModal({
  target,
  users,
  onClose,
  onDone,
}: {
  target: AdminTemplate;
  users: AdminUserRow[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [userId, setUserId] = useState("");
  const [ownerCanEdit, setOwnerCanEdit] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (!userId) {
      setError("Pick a target user.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const r = await apiFetch(
        `/api/admin/templates/${encodeURIComponent(target.id)}/instantiate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_id: userId,
            owner_can_edit: ownerCanEdit,
          }),
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
      setDone(true);
      setTimeout(onDone, 900);
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ModalShell title={`Instantiate ${target.slug}`} onClose={onClose}>
      <form onSubmit={submit} className="p-5 space-y-4 text-sm">
        {done ? (
          <div className="text-emerald-300">Workspace created.</div>
        ) : (
          <>
            <p className="text-gray-300">
              Creates a new workspace for the chosen user, seeded from this
              template. Rejects if the user already has a workspace from this
              template (delete the existing one first to re-seed).
            </p>
            <Field label="Target user">
              <select
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
                className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm"
              >
                <option value="">Pick a user…</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.username}
                  </option>
                ))}
              </select>
            </Field>
            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={ownerCanEdit}
                onChange={(e) => setOwnerCanEdit(e.target.checked)}
                className="mt-1"
              />
              <span className="flex flex-col">
                <span>Owner can edit</span>
                <span className="text-xs text-gray-500">
                  Lets the recipient change system prompt + enabled tools on
                  their copy.
                </span>
              </span>
            </label>

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
                type="submit"
                disabled={submitting}
                className="text-sm px-3 py-1.5 rounded bg-emerald-500/20 border border-emerald-500/40 text-emerald-200 hover:bg-emerald-500/30 disabled:opacity-50"
              >
                {submitting ? "Creating…" : "Instantiate"}
              </button>
            </div>
          </>
        )}
      </form>
    </ModalShell>
  );
}
