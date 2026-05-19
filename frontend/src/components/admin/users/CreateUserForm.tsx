"use client";

import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "@/utils/apiClient";
import { ToolPicker } from "@/components/ToolPicker";
import { Field } from "@/components/admin/Field";
import { Checkbox } from "./Checkbox";
import {
  PASSWORD_MIN,
  type StarterTemplateSelection,
  type WorkspaceTemplate,
} from "./types";

export function CreateUserForm({ onCreated }: { onCreated: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [canCreateWorkspaces, setCanCreateWorkspaces] = useState(true);
  const [allowedTools, setAllowedTools] = useState<string[]>([]);
  const [templates, setTemplates] = useState<WorkspaceTemplate[]>([]);
  const [selectedTemplates, setSelectedTemplates] = useState<
    Record<string, StarterTemplateSelection>
  >({});
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [formSuccess, setFormSuccess] = useState<string | null>(null);

  useEffect(() => {
    apiFetch("/api/admin/templates")
      .then((r) => (r.ok ? r.json() : []))
      .then((body: WorkspaceTemplate[]) =>
        setTemplates(Array.isArray(body) ? body : []),
      )
      .catch(() => setTemplates([]));
  }, []);

  const toggleAllowedTool = (name: string) => {
    setAllowedTools((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  };

  const toggleTemplate = (id: string) => {
    setSelectedTemplates((prev) => {
      const next = { ...prev };
      if (next[id]) {
        delete next[id];
      } else {
        next[id] = { template_id: id, owner_can_edit: false };
      }
      return next;
    });
  };

  const toggleOwnerCanEdit = (id: string) => {
    setSelectedTemplates((prev) => {
      if (!prev[id]) return prev;
      return {
        ...prev,
        [id]: { ...prev[id], owner_can_edit: !prev[id].owner_can_edit },
      };
    });
  };

  const onSubmit = async (ev: FormEvent) => {
    ev.preventDefault();
    setFormError(null);
    setFormSuccess(null);

    if (username.trim().length < 1) {
      setFormError("Username is required.");
      return;
    }
    if (password.length < PASSWORD_MIN) {
      setFormError(`Password must be at least ${PASSWORD_MIN} characters.`);
      return;
    }

    setSubmitting(true);
    try {
      const r = await apiFetch("/api/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: username.trim(),
          password,
          is_admin: isAdmin,
          can_create_workspaces: canCreateWorkspaces,
          allowed_tools: allowedTools,
          starter_templates: Object.values(selectedTemplates),
        }),
      });
      if (!r.ok) {
        let detail = `Failed (${r.status})`;
        try {
          const body = await r.json();
          if (typeof body?.detail === "string") detail = body.detail;
        } catch {
          // body wasn't JSON; keep the status code message
        }
        setFormError(detail);
        return;
      }
      const created = await r.json();
      const seededCount = Object.keys(selectedTemplates).length;
      setFormSuccess(
        seededCount > 0
          ? `Created ${created.username} with ${seededCount} starter workspace${seededCount === 1 ? "" : "s"}.`
          : `Created ${created.username}.`,
      );
      // Reset only the secret/sensitive bits; keep the role toggles as the
      // admin probably wants to make several users of the same shape.
      setUsername("");
      setPassword("");
      setAllowedTools([]);
      setSelectedTemplates({});
      onCreated();
    } catch (e) {
      setFormError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="border border-[#2a2a2c] rounded p-5 bg-[#161617]">
      <h3 className="text-sm font-semibold mb-4">Create user</h3>
      <form onSubmit={onSubmit} className="space-y-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Username">
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="off"
              className="w-full bg-[#1e1e1f] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm"
              placeholder="e.g. tester"
            />
          </Field>
          <Field label={`Password (min ${PASSWORD_MIN} chars)`}>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              className="w-full bg-[#1e1e1f] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm"
            />
          </Field>
        </div>

        <div className="flex flex-wrap gap-6">
          <Checkbox
            label="Admin"
            checked={isAdmin}
            onChange={setIsAdmin}
            hint="Can access /admin and manage other users"
          />
          <Checkbox
            label="Can create workspaces"
            checked={canCreateWorkspaces}
            onChange={setCanCreateWorkspaces}
            hint="Allowed to add new workspaces in the chat sidebar"
          />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-gray-400 mb-1">
              Allowed tools
            </label>
            <div className="max-h-60 overflow-y-auto rounded border border-[#2a2a2c] bg-[#131314] p-2 custom-scrollbar">
              <ToolPicker selected={allowedTools} onToggle={toggleAllowedTool} />
            </div>
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1">
              Starter workspaces
            </label>
            {templates.length === 0 ? (
              <div className="text-xs text-gray-500 rounded border border-[#2a2a2c] bg-[#131314] p-3">
                No workspace templates exist yet. The new user will start with
                no workspaces and won&apos;t be able to use the AI until they
                create one (requires &quot;Can create workspaces&quot; checked above).
              </div>
            ) : (
              <div className="max-h-60 overflow-y-auto space-y-1.5 border border-[#2a2a2c] rounded p-3 bg-[#131314] custom-scrollbar">
                {templates.map((t) => {
                  const selected = !!selectedTemplates[t.id];
                  return (
                    <div
                      key={t.id}
                      className="flex items-center justify-between gap-3"
                    >
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={selected}
                          onChange={() => toggleTemplate(t.id)}
                        />
                        <span className="text-sm">{t.display_name}</span>
                        <span className="text-xs text-gray-500 font-mono">
                          {t.slug}
                        </span>
                      </label>
                      {selected && (
                        <label className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={selectedTemplates[t.id].owner_can_edit}
                            onChange={() => toggleOwnerCanEdit(t.id)}
                          />
                          Owner can edit
                        </label>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {formError && (
          <div className="text-sm text-red-400">{formError}</div>
        )}
        {formSuccess && (
          <div className="text-sm text-emerald-400">{formSuccess}</div>
        )}

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={submitting}
            className="text-sm px-4 py-1.5 rounded bg-[#2a2a2c] hover:bg-[#3a3a3c] disabled:opacity-50"
          >
            {submitting ? "Creating…" : "Create user"}
          </button>
        </div>
      </form>
    </section>
  );
}
