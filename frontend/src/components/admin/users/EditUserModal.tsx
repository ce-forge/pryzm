"use client";

import { FormEvent, useState } from "react";
import { apiFetch } from "@/utils/apiClient";
import { ToolPicker } from "@/components/ToolPicker";
import { ModalShell } from "@/components/admin/ModalShell";
import { Field } from "@/components/admin/Field";
import { Checkbox } from "./Checkbox";
import type { AdminUser } from "./types";

export function EditUserModal({
  target,
  onClose,
  onDone,
}: {
  target: AdminUser;
  onClose: () => void;
  onDone: () => void;
}) {
  const [username, setUsername] = useState(target.username);
  const [email, setEmail] = useState(target.email ?? "");
  const [isAdmin, setIsAdmin] = useState(target.is_admin);
  const [canCreateWorkspaces, setCanCreateWorkspaces] = useState(
    target.can_create_workspaces,
  );
  const [allowedTools, setAllowedTools] = useState<string[]>(
    target.allowed_tools ?? [],
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleAllowedTool = (name: string) => {
    setAllowedTools((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      // Send only fields that actually changed. PATCH treats missing keys
      // as unset, so this is enough to keep the audit's changed_fields
      // payload clean.
      const patch: Record<string, unknown> = {};
      if (username.trim() !== target.username) patch.username = username.trim();
      const normalizedEmail = email.trim() || null;
      if (normalizedEmail !== (target.email ?? null)) patch.email = normalizedEmail;
      if (isAdmin !== target.is_admin) patch.is_admin = isAdmin;
      if (canCreateWorkspaces !== target.can_create_workspaces) {
        patch.can_create_workspaces = canCreateWorkspaces;
      }
      if (
        JSON.stringify([...allowedTools].sort()) !==
        JSON.stringify([...(target.allowed_tools ?? [])].sort())
      ) {
        patch.allowed_tools = allowedTools;
      }

      if (Object.keys(patch).length === 0) {
        onClose();
        return;
      }

      const r = await apiFetch(`/api/admin/users/${encodeURIComponent(target.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
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
      onDone();
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ModalShell title={`Edit ${target.username}`} onClose={onClose}>
      <form onSubmit={submit} className="p-5 space-y-4">
        <Field label="Username">
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm"
            autoComplete="off"
          />
        </Field>

        <Field label="Email (optional)">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm"
            autoComplete="off"
          />
        </Field>

        <div className="flex flex-wrap gap-6">
          <Checkbox
            label="Admin"
            checked={isAdmin}
            onChange={setIsAdmin}
          />
          <Checkbox
            label="Can create workspaces"
            checked={canCreateWorkspaces}
            onChange={setCanCreateWorkspaces}
          />
        </div>

        <Field label="Allowed tools">
          <div className="max-h-60 overflow-y-auto rounded border border-[#2a2a2c] bg-[#131314] p-2 custom-scrollbar">
            <ToolPicker selected={allowedTools} onToggle={toggleAllowedTool} />
          </div>
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
            {submitting ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}
