"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/utils/apiClient";
import Identicon from "@/components/Identicon";
import { StatsPanel } from "@/components/admin/StatsPanel";
import { StatusBadge } from "@/components/admin/StatusBadge";
import {
  BugDetailModal,
  CATEGORY_LABELS,
  type AdminBugReport,
} from "@/components/admin/bugReports/BugDetailModal";
import type { AdminUserRow } from "@/types/admin";

const STATUS_FILTERS = [
  { value: "open-or-acknowledged", label: "Open + acknowledged" },
  { value: "open", label: "Open" },
  { value: "acknowledged", label: "Acknowledged" },
  { value: "resolved", label: "Resolved" },
  { value: "dismissed", label: "Dismissed" },
  { value: "", label: "All" },
];

export default function AdminBugReportsPage() {
  const [bugs, setBugs] = useState<AdminBugReport[]>([]);
  const [users, setUsers] = useState<AdminUserRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [statusFilter, setStatusFilter] = useState<string>("open-or-acknowledged");
  const [userFilter, setUserFilter] = useState<string>("");
  const [categoryFilter, setCategoryFilter] = useState<string>("");
  const [selected, setSelected] = useState<AdminBugReport | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (statusFilter && statusFilter !== "open-or-acknowledged") {
        params.set("status", statusFilter);
      }
      if (userFilter) params.set("user_id", userFilter);
      if (categoryFilter) params.set("category", categoryFilter);
      const r = await apiFetch(`/api/admin/bug-reports?${params.toString()}`);
      if (!r.ok) {
        setError(`Failed (${r.status})`);
        return;
      }
      let body: AdminBugReport[] = await r.json();
      if (statusFilter === "open-or-acknowledged") {
        body = body.filter(
          (b) => b.status === "open" || b.status === "acknowledged",
        );
      }
      setBugs(body);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [statusFilter, userFilter, categoryFilter]);

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

  const byStatus = {
    open: bugs.filter((b) => b.status === "open").length,
    acknowledged: bugs.filter((b) => b.status === "acknowledged").length,
    resolved: bugs.filter((b) => b.status === "resolved").length,
    dismissed: bugs.filter((b) => b.status === "dismissed").length,
  };

  return (
    <div className="flex gap-6 max-w-7xl">
      <div className="flex-1 min-w-0">
      <div className="flex flex-wrap items-end gap-3 mb-4">
        <FilterColumn label="Status">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-[#1e1e1f] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm min-w-44"
          >
            {STATUS_FILTERS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </FilterColumn>

        <FilterColumn label="Reporter">
          <select
            value={userFilter}
            onChange={(e) => setUserFilter(e.target.value)}
            className="bg-[#1e1e1f] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm min-w-44"
          >
            <option value="">All users</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.username}
              </option>
            ))}
          </select>
        </FilterColumn>

        <FilterColumn label="Category">
          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="bg-[#1e1e1f] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm min-w-44"
          >
            <option value="">All categories</option>
            {Object.entries(CATEGORY_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </FilterColumn>
      </div>

      {error && <div className="mb-3 text-sm text-red-400">{error}</div>}

      <div className="border border-[#2a2a2c] rounded overflow-x-auto">
        <table className="w-full text-sm min-w-[700px]">
          <thead className="bg-[#1e1e1f] text-xs text-gray-400 text-left">
            <tr>
              <th className="px-3 py-2 font-medium w-40">When</th>
              <th className="px-3 py-2 font-medium w-28">Reporter</th>
              <th className="px-3 py-2 font-medium w-24">Status</th>
              <th className="px-3 py-2 font-medium w-32">Category</th>
              <th className="px-3 py-2 font-medium">Message</th>
            </tr>
          </thead>
          <tbody>
            {bugs.length === 0 && !loading && (
              <tr>
                <td
                  colSpan={5}
                  className="px-3 py-6 text-center text-gray-500"
                >
                  No alerts match the current filters.
                </td>
              </tr>
            )}
            {bugs.map((b) => (
              <tr
                key={b.id}
                onClick={() => setSelected(b)}
                className="border-t border-[#2a2a2c] hover:bg-[#1a1a1b] cursor-pointer"
              >
                <td className="px-3 py-2 text-xs text-gray-400 whitespace-nowrap">
                  {b.created_at ? (
                    <>
                      <div>{new Date(b.created_at).toLocaleDateString()}</div>
                      <div>{new Date(b.created_at).toLocaleTimeString()}</div>
                    </>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-3 py-2">
                  <span className="inline-flex items-center gap-2">
                    <Identicon seed={b.user_display_name} size={18} />
                    {b.user_display_name}
                  </span>
                </td>
                <td className="px-3 py-2">
                  <StatusBadge status={b.status} />
                </td>
                <td className="px-3 py-2 text-xs text-gray-300">
                  {CATEGORY_LABELS[b.category] ?? b.category}
                </td>
                <td className="px-3 py-2 text-xs text-gray-300 truncate max-w-md">
                  {b.message.length > 120
                    ? b.message.slice(0, 120) + "…"
                    : b.message}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected && (
        <BugDetailModal
          bug={selected}
          onClose={() => setSelected(null)}
          onChanged={async () => {
            await load();
            setSelected(null);
          }}
        />
      )}
      </div>

      <aside className="hidden xl:block w-72 shrink-0 space-y-4">
        <StatsPanel
          title="At a glance"
          rows={[
            { label: "Visible", value: bugs.length },
            { label: "Open", value: byStatus.open },
            { label: "Acknowledged", value: byStatus.acknowledged },
            { label: "Resolved", value: byStatus.resolved },
            { label: "Dismissed", value: byStatus.dismissed },
          ]}
        />
      </aside>
    </div>
  );
}

function FilterColumn({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-gray-400">{label}</span>
      {children}
    </div>
  );
}
