"use client";

import { FormEvent, useState } from "react";
import { apiFetch } from "@/utils/apiClient";
import { ToolPicker } from "@/components/ToolPicker";
import { ModalShell } from "@/components/admin/ModalShell";
import { Field } from "@/components/admin/Field";
import { ColorPicker } from "./ColorPicker";

export function TemplateCreateModal({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: () => void;
}) {
  const [slug, setSlug] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [color, setColor] = useState<string | null>(null);
  const [enabledTools, setEnabledTools] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleTool = (name: string) => {
    setEnabledTools((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  };

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    if (!slug.trim() || !displayName.trim()) {
      setError("Slug and display name are required.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const r = await apiFetch("/api/admin/templates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          slug: slug.trim(),
          display_name: displayName.trim(),
          system_prompt: systemPrompt,
          enabled_tools: enabledTools,
          color,
        }),
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
    <ModalShell title="New template" onClose={onClose} size="max-w-lg">
      <form onSubmit={submit} className="p-5 space-y-4">
        <p className="text-xs text-gray-400">
          Slug is stable forever — it shows up in cloned-workspace URLs and in
          audit logs. Pick something short and lowercase. Everything else can
          be edited later.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Slug">
            <input
              type="text"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm font-mono"
              placeholder="e.g. devops"
              autoComplete="off"
            />
          </Field>
          <Field label="Display name">
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm"
              placeholder="e.g. DevOps"
            />
          </Field>
        </div>
        <Field label="System prompt">
          <textarea
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            rows={5}
            className="w-full bg-[#131314] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm resize-y font-mono"
          />
        </Field>
        <Field label="Enabled tools">
          <ToolPicker selected={enabledTools} onToggle={toggleTool} />
        </Field>
        <Field label="Color">
          <ColorPicker value={color} onChange={setColor} />
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
            {submitting ? "Creating…" : "Create"}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}
