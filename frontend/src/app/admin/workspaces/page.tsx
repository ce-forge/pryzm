"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/utils/apiClient";

interface AdminWorkspace {
  id: string;
  slug: string;
  display_name: string;
  user_id: string | null;
  template_id: string | null;
  owner_can_edit: boolean;
  owner_username: string | null;
  template_display_name: string | null;
  color: string | null;
  created_at: string | null;
}

interface AdminTemplate {
  id: string;
  slug: string;
  display_name: string;
  color: string | null;
}

interface AdminUserRow {
  id: string;
  username: string;
}

type SubTab = "templates" | "workspaces";

export default function AdminWorkspacesPage() {
  const [subTab, setSubTab] = useState<SubTab>("workspaces");
  return (
    <div className="max-w-6xl">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold">Workspaces</h2>
        <div className="flex gap-1 border border-[#2a2a2c] rounded p-0.5 bg-[#1e1e1f]">
          <SubTabButton
            label="All workspaces"
            active={subTab === "workspaces"}
            onClick={() => setSubTab("workspaces")}
          />
          <SubTabButton
            label="Templates"
            active={subTab === "templates"}
            onClick={() => setSubTab("templates")}
          />
        </div>
      </div>

      {subTab === "workspaces" ? <AllWorkspacesView /> : <TemplatesView />}
    </div>
  );
}

function SubTabButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "text-xs px-3 py-1 rounded " +
        (active
          ? "bg-[#2a2a2c] text-[#e3e3e3]"
          : "text-gray-400 hover:text-[#e3e3e3]")
      }
    >
      {label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// All workspaces view
// ---------------------------------------------------------------------------

function AllWorkspacesView() {
  const [workspaces, setWorkspaces] = useState<AdminWorkspace[]>([]);
  const [users, setUsers] = useState<AdminUserRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Filters
  const [userFilter, setUserFilter] = useState<string>("");
  const [orphanedOnly, setOrphanedOnly] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (orphanedOnly) params.set("orphaned", "true");
      else if (userFilter) params.set("user_id", userFilter);
      const r = await apiFetch(`/api/admin/workspaces?${params.toString()}`);
      if (!r.ok) {
        setError(`Failed (${r.status})`);
        return;
      }
      const body = await r.json();
      setWorkspaces(Array.isArray(body) ? body : []);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [userFilter, orphanedOnly]);

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

  const orphanCount = useMemo(
    () => workspaces.filter((w) => !w.user_id).length,
    [workspaces],
  );

  const deleteWorkspace = async (w: AdminWorkspace) => {
    const ok = window.confirm(
      `Delete workspace "${w.display_name}" (slug ${w.slug})?\n\n` +
        `This cascades to its sessions, folders, and documents. Cannot be undone.`,
    );
    if (!ok) return;
    const r = await apiFetch(`/api/admin/workspaces/${w.id}`, {
      method: "DELETE",
    });
    if (!r.ok) {
      window.alert(`Delete failed (${r.status})`);
      return;
    }
    await load();
  };

  const toggleOwnerCanEdit = async (w: AdminWorkspace) => {
    const r = await apiFetch(`/api/admin/workspaces/${w.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ owner_can_edit: !w.owner_can_edit }),
    });
    if (!r.ok) {
      window.alert(`Update failed (${r.status})`);
      return;
    }
    await load();
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-gray-400">Owner</span>
          <select
            value={userFilter}
            onChange={(e) => {
              setUserFilter(e.target.value);
              setOrphanedOnly(false);
            }}
            disabled={orphanedOnly}
            className="bg-[#1e1e1f] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm min-w-44 disabled:opacity-50"
          >
            <option value="">All users</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.username}
              </option>
            ))}
          </select>
        </div>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={orphanedOnly}
            onChange={(e) => {
              setOrphanedOnly(e.target.checked);
              if (e.target.checked) setUserFilter("");
            }}
          />
          <span className="text-sm">Orphaned only</span>
          <span className="text-xs text-gray-500">(no owner)</span>
        </label>

        {orphanCount > 0 && !orphanedOnly && (
          <span className="text-xs text-amber-400">
            {orphanCount} orphaned in current view
          </span>
        )}
      </div>

      {error && <div className="text-sm text-red-400">{error}</div>}

      <div className="border border-[#2a2a2c] rounded overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[#1e1e1f] text-xs text-gray-400 text-left">
            <tr>
              <th className="px-3 py-2 font-medium">Name</th>
              <th className="px-3 py-2 font-medium w-32">Owner</th>
              <th className="px-3 py-2 font-medium w-40">Template</th>
              <th className="px-3 py-2 font-medium w-28">Owner can edit</th>
              <th className="px-3 py-2 font-medium w-44">Created</th>
              <th className="px-3 py-2 font-medium w-32">Actions</th>
            </tr>
          </thead>
          <tbody>
            {workspaces.length === 0 && !loading && (
              <tr>
                <td
                  colSpan={6}
                  className="px-3 py-6 text-center text-gray-500"
                >
                  No workspaces match the current filters.
                </td>
              </tr>
            )}
            {workspaces.map((w) => (
              <tr key={w.id} className="border-t border-[#2a2a2c]">
                <td className="px-3 py-2">
                  <div>{w.display_name}</div>
                  <div className="font-mono text-[10px] text-gray-500">
                    {w.slug}
                  </div>
                </td>
                <td className="px-3 py-2">
                  {w.owner_username ?? (
                    <span className="text-amber-400">(orphan)</span>
                  )}
                </td>
                <td className="px-3 py-2 text-xs text-gray-400">
                  {w.template_display_name ?? "—"}
                </td>
                <td className="px-3 py-2">
                  <button
                    type="button"
                    onClick={() => toggleOwnerCanEdit(w)}
                    className={
                      "text-xs px-2 py-0.5 rounded border " +
                      (w.owner_can_edit
                        ? "bg-emerald-500/15 border-emerald-500/30 text-emerald-300"
                        : "border-[#2a2a2c] text-gray-400")
                    }
                  >
                    {w.owner_can_edit ? "yes" : "no"}
                  </button>
                </td>
                <td className="px-3 py-2 text-xs text-gray-400">
                  {w.created_at
                    ? new Date(w.created_at).toLocaleString()
                    : "—"}
                </td>
                <td className="px-3 py-2">
                  <button
                    type="button"
                    onClick={() => deleteWorkspace(w)}
                    className="text-xs px-2 py-1 rounded bg-red-500/15 border border-red-500/30 text-red-300 hover:bg-red-500/25"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Templates view (read + delete for v1; create/edit/push come later)
// ---------------------------------------------------------------------------

function TemplatesView() {
  const [templates, setTemplates] = useState<AdminTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    <div className="space-y-4">
      <p className="text-xs text-gray-400">
        Templates seed new users&apos; starter workspaces. Create / edit / push
        operations ship in a follow-up slice — for now this view is read +
        delete only.
      </p>

      {error && <div className="text-sm text-red-400">{error}</div>}

      <div className="border border-[#2a2a2c] rounded overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[#1e1e1f] text-xs text-gray-400 text-left">
            <tr>
              <th className="px-3 py-2 font-medium">Display name</th>
              <th className="px-3 py-2 font-medium w-32">Slug</th>
              <th className="px-3 py-2 font-medium w-24">Color</th>
              <th className="px-3 py-2 font-medium w-32">Actions</th>
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
                <td className="px-3 py-2">{t.display_name}</td>
                <td className="px-3 py-2 font-mono text-xs text-gray-400">
                  {t.slug}
                </td>
                <td className="px-3 py-2 text-xs text-gray-400">
                  {t.color ?? "—"}
                </td>
                <td className="px-3 py-2">
                  <button
                    type="button"
                    onClick={() => deleteTemplate(t)}
                    className="text-xs px-2 py-1 rounded bg-red-500/15 border border-red-500/30 text-red-300 hover:bg-red-500/25"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
