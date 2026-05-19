"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/utils/apiClient";
import Identicon from "@/components/Identicon";
import { StatsPanel } from "@/components/admin/StatsPanel";
import { WorkspaceEditModal } from "./WorkspaceEditModal";
import { WorkspacePromoteToTemplateModal } from "./WorkspacePromoteToTemplateModal";
import type { AdminWorkspace, AdminUserRow } from "./types";

export function AllWorkspacesView() {
  const [workspaces, setWorkspaces] = useState<AdminWorkspace[]>([]);
  const [users, setUsers] = useState<AdminUserRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Filters
  const [userFilter, setUserFilter] = useState<string>("");
  const [orphanedOnly, setOrphanedOnly] = useState(false);

  // Modal state
  const [editWorkspace, setEditWorkspace] = useState<AdminWorkspace | null>(null);
  const [promoteWorkspace, setPromoteWorkspace] = useState<AdminWorkspace | null>(null);

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

  const withTemplate = workspaces.filter((w) => w.template_id).length;

  return (
    <div className="flex gap-6">
      <div className="flex-1 min-w-0 space-y-4">
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

      <div className="border border-[#2a2a2c] rounded overflow-x-auto">
        <table className="w-full text-sm min-w-[900px]">
          <thead className="bg-[#1e1e1f] text-xs text-gray-400 text-left">
            <tr>
              <th className="px-3 py-2 font-medium max-md:sticky max-md:left-0 max-md:bg-[#1e1e1f]">Name</th>
              <th className="px-3 py-2 font-medium w-32">Owner</th>
              <th className="px-3 py-2 font-medium w-40">Template</th>
              <th className="px-3 py-2 font-medium w-28">Owner can edit</th>
              <th className="px-3 py-2 font-medium w-44">Created</th>
              <th className="px-3 py-2 font-medium w-64">Actions</th>
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
                <td className="px-3 py-2 max-md:sticky max-md:left-0 max-md:bg-[#131314]">
                  <div>{w.display_name}</div>
                  <div className="font-mono text-[10px] text-gray-500">
                    {w.slug}
                  </div>
                </td>
                <td className="px-3 py-2">
                  {w.owner_username ? (
                    <span className="inline-flex items-center gap-2">
                      <Identicon seed={w.owner_username} size={20} />
                      {w.owner_username}
                    </span>
                  ) : (
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
                  {w.created_at ? (
                    <>
                      <div>{new Date(w.created_at).toLocaleDateString()}</div>
                      <div>{new Date(w.created_at).toLocaleTimeString()}</div>
                    </>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1 whitespace-nowrap">
                    <button
                      type="button"
                      onClick={() => setEditWorkspace(w)}
                      className="text-xs px-2 py-0.5 rounded border border-[#2a2a2c] hover:bg-[#2a2a2c] text-gray-300"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => setPromoteWorkspace(w)}
                      className="text-xs px-2 py-0.5 rounded border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/15"
                    >
                      Make template
                    </button>
                    <button
                      type="button"
                      onClick={() => deleteWorkspace(w)}
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

      {editWorkspace && (
        <WorkspaceEditModal
          target={editWorkspace}
          onClose={() => setEditWorkspace(null)}
          onDone={() => {
            setEditWorkspace(null);
            load();
          }}
        />
      )}

      {promoteWorkspace && (
        <WorkspacePromoteToTemplateModal
          target={promoteWorkspace}
          onClose={() => setPromoteWorkspace(null)}
          onDone={() => setPromoteWorkspace(null)}
        />
      )}
      </div>

      <aside className="hidden xl:block w-72 shrink-0 space-y-4">
        <StatsPanel
          title="At a glance"
          rows={[
            { label: "Visible", value: workspaces.length },
            { label: "Orphaned", value: orphanCount },
            { label: "From template", value: withTemplate },
            { label: "User-created", value: workspaces.length - withTemplate },
          ]}
        />
      </aside>
    </div>
  );
}
