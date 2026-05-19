"use client";

import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "@/utils/apiClient";
import { ToolPicker } from "@/components/ToolPicker";
import { ModalShell } from "@/components/admin/ModalShell";
import { Field } from "@/components/admin/Field";
import { ColorPicker } from "./ColorPicker";
import type { AdminWorkspace } from "./types";

export function WorkspaceEditModal({
  target,
  onClose,
  onDone,
}: {
  target: AdminWorkspace;
  onClose: () => void;
  onDone: () => void;
}) {
  const [displayName, setDisplayName] = useState(target.display_name);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [color, setColor] = useState<string | null>(target.color ?? null);
  const [enabledTools, setEnabledTools] = useState<string[]>([]);
  const [ownerCanEdit, setOwnerCanEdit] = useState<boolean>(target.owner_can_edit);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch(`/api/admin/workspaces/${encodeURIComponent(target.id)}`)
      .then(async (r) => {
        if (cancelled) return;
        if (!r.ok) {
          setError(`Failed to load (${r.status})`);
          return;
        }
        const body = await r.json();
        setDisplayName(body.display_name ?? "");
        setSystemPrompt(body.system_prompt ?? "");
        setColor(body.color ?? null);
        setEnabledTools(Array.isArray(body.enabled_tools) ? body.enabled_tools : []);
        setOwnerCanEdit(!!body.owner_can_edit);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [target.id]);

  const toggleTool = (name: string) => {
    setEnabledTools((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const r = await apiFetch(
        `/api/admin/workspaces/${encodeURIComponent(target.id)}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            display_name: displayName.trim(),
            system_prompt: systemPrompt,
            enabled_tools: enabledTools,
            color,
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
      onDone();
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ModalShell title={`Edit ${target.slug}`} onClose={onClose} size="max-w-lg">
      {loading ? (
        <div className="p-6 text-sm text-gray-400">Loading…</div>
      ) : (
        <form onSubmit={submit} className="p-5 space-y-4">
          <Field label="Display name">
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm"
            />
          </Field>
          <Field label="System prompt">
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              rows={8}
              className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm resize-y font-mono"
            />
          </Field>
          <Field label="Enabled tools">
            <ToolPicker selected={enabledTools} onToggle={toggleTool} />
          </Field>
          <Field label="Color">
            <ColorPicker value={color} onChange={setColor} />
          </Field>
          <label className="flex items-center gap-2 cursor-pointer text-sm">
            <input
              type="checkbox"
              checked={ownerCanEdit}
              onChange={(e) => setOwnerCanEdit(e.target.checked)}
            />
            <span>Owner can edit</span>
          </label>

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
      )}
    </ModalShell>
  );
}
