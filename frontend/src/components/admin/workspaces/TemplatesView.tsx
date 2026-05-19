"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/utils/apiClient";
import { StatsPanel } from "@/components/admin/StatsPanel";
import { TemplateCreateModal } from "./TemplateCreateModal";
import { TemplateEditModal } from "./TemplateEditModal";
import { TemplateApplyModal } from "./TemplateApplyModal";
import type { AdminTemplate, AdminUserRow } from "./types";

export function TemplatesView() {
  const [templates, setTemplates] = useState<AdminTemplate[]>([]);
  const [users, setUsers] = useState<AdminUserRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Modal state
  const [showCreate, setShowCreate] = useState(false);
  const [editTemplate, setEditTemplate] = useState<AdminTemplate | null>(null);
  const [applyTemplate, setApplyTemplate] = useState<AdminTemplate | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await apiFetch("/api/admin/templates");
      if (!r.ok) {
        setError(`Failed (${r.status})`);
        return;
      }
      const body = await r.json();
      setTemplates(Array.isArray(body) ? body : []);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  useEffect(() => {
    apiFetch("/api/admin/users")
      .then((r) => (r.ok ? r.json() : []))
      .then((body: AdminUserRow[]) =>
        setUsers(Array.isArray(body) ? body : []),
      );
  }, []);

  const deleteTemplate = async (t: AdminTemplate) => {
    const ok = window.confirm(
      `Delete template "${t.display_name}"?\n\n` +
        `User workspaces instantiated from this template are not affected — ` +
        `their template_id is set to NULL.`,
    );
    if (!ok) return;
    const r = await apiFetch(`/api/admin/templates/${t.id}`, {
      method: "DELETE",
    });
    if (!r.ok) {
      window.alert(`Delete failed (${r.status})`);
      return;
    }
    await load();
  };

  return (
    <div className="flex gap-6">
      <div className="flex-1 min-w-0 space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-400">
          Templates seed new users&apos; starter workspaces. Push to apply
          the template across users — each user can be updated, adopted
          from an existing slug-match, or created fresh.
        </p>
        <button
          type="button"
          onClick={() => setShowCreate(true)}
          className="text-sm px-3 py-1.5 rounded bg-[#2a2a2c] hover:bg-[#3a3a3c]"
        >
          + New template
        </button>
      </div>

      {error && <div className="text-sm text-red-400">{error}</div>}

      <div className="border border-[#2a2a2c] rounded overflow-x-auto">
        <table className="w-full text-sm min-w-[600px]">
          <thead className="bg-[#1e1e1f] text-xs text-gray-400 text-left">
            <tr>
              <th className="px-3 py-2 font-medium max-md:sticky max-md:left-0 max-md:bg-[#1e1e1f]">Display name</th>
              <th className="px-3 py-2 font-medium w-32">Slug</th>
              <th className="px-3 py-2 font-medium w-24">Color</th>
              <th className="px-3 py-2 font-medium w-72">Actions</th>
            </tr>
          </thead>
          <tbody>
            {templates.length === 0 && !loading && (
              <tr>
                <td
                  colSpan={4}
                  className="px-3 py-6 text-center text-gray-500"
                >
                  No templates yet.
                </td>
              </tr>
            )}
            {templates.map((t) => (
              <tr key={t.id} className="border-t border-[#2a2a2c]">
                <td className="px-3 py-2 max-md:sticky max-md:left-0 max-md:bg-[#131314]">{t.display_name}</td>
                <td className="px-3 py-2 font-mono text-xs text-gray-400">
                  {t.slug}
                </td>
                <td className="px-3 py-2 text-xs text-gray-400">
                  {t.color ?? "—"}
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1 whitespace-nowrap">
                    <button
                      type="button"
                      onClick={() => setEditTemplate(t)}
                      className="text-xs px-2 py-0.5 rounded border border-[#2a2a2c] hover:bg-[#2a2a2c] text-gray-300"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => setApplyTemplate(t)}
                      className="text-xs px-2 py-0.5 rounded border border-sky-500/30 text-sky-300 hover:bg-sky-500/15"
                    >
                      Push…
                    </button>
                    <button
                      type="button"
                      onClick={() => deleteTemplate(t)}
                      className="text-xs px-2 py-0.5 rounded border border-red-500/30 text-red-300 hover:bg-red-500/15"
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showCreate && (
        <TemplateCreateModal
          onClose={() => setShowCreate(false)}
          onDone={() => {
            setShowCreate(false);
            load();
          }}
        />
      )}

      {editTemplate && (
        <TemplateEditModal
          target={editTemplate}
          onClose={() => setEditTemplate(null)}
          onDone={() => {
            setEditTemplate(null);
            load();
          }}
        />
      )}

      {applyTemplate && (
        <TemplateApplyModal
          target={applyTemplate}
          onClose={() => setApplyTemplate(null)}
          onDone={() => {
            setApplyTemplate(null);
            load();
          }}
        />
      )}
      </div>

      <aside className="hidden xl:block w-72 shrink-0 space-y-4">
        <StatsPanel
          title="At a glance"
          rows={[
            { label: "Templates", value: templates.length },
            { label: "Users", value: users.length },
          ]}
        />
      </aside>
    </div>
  );
}
