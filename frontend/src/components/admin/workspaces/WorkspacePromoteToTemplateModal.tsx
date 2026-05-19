"use client";

import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "@/utils/apiClient";
import { ModalShell } from "./ModalShell";
import { Field } from "./Field";
import type { AdminWorkspace } from "./types";

export function WorkspacePromoteToTemplateModal({
  target,
  onClose,
  onDone,
}: {
  target: AdminWorkspace;
  onClose: () => void;
  onDone: () => void;
}) {
  // Pre-fetch the workspace's settings so the new template inherits them
  // (system_prompt, enabled_tools, engine_config). slug + display_name are
  // admin-chosen; everything else comes from the source workspace.
  const [slug, setSlug] = useState(target.slug);
  const [displayName, setDisplayName] = useState(target.display_name);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [enabledTools, setEnabledTools] = useState<string[]>([]);
  const [engineConfig, setEngineConfig] = useState<Record<string, unknown>>({});
  const [color, setColor] = useState<string | null>(target.color ?? null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiFetch(`/api/admin/workspaces/${encodeURIComponent(target.id)}`)
      .then(async (r) => {
        if (cancelled) return;
        if (!r.ok) {
          setError(`Failed to load source workspace (${r.status})`);
          return;
        }
        const body = await r.json();
        setSystemPrompt(body.system_prompt ?? "");
        setEnabledTools(Array.isArray(body.enabled_tools) ? body.enabled_tools : []);
        setEngineConfig(body.engine_config ?? {});
        setColor(body.color ?? null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [target.id]);

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
          engine_config: engineConfig,
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
      setDone(true);
      setTimeout(onDone, 900);
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ModalShell title={`Make template from ${target.slug}`} onClose={onClose} size="max-w-lg">
      {loading ? (
        <div className="p-6 text-sm text-gray-400">Loading workspace settings…</div>
      ) : done ? (
        <div className="p-5 text-sm text-emerald-300">Template created.</div>
      ) : (
        <form onSubmit={submit} className="p-5 space-y-4">
          <p className="text-xs text-gray-400">
            Creates a new template seeded from this workspace&apos;s system
            prompt, enabled tools, color, and engine config. Pick a stable
            slug — it shows up in cloned-workspace URLs and audit logs.
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
              />
            </Field>
          </div>

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
              className="text-sm px-3 py-1.5 rounded bg-emerald-500/20 border border-emerald-500/40 text-emerald-200 hover:bg-emerald-500/30 disabled:opacity-50"
            >
              {submitting ? "Creating…" : "Create template"}
            </button>
          </div>
        </form>
      )}
    </ModalShell>
  );
}
