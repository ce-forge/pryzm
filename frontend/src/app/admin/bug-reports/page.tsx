"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/utils/apiClient";

interface AdminBugReport {
  id: string;
  user_id: string | null;
  user_display_name: string;
  workspace_id: string | null;
  session_id: string | null;
  category: string;
  message: string;
  payload: Record<string, unknown>;
  status: string;
  resolved_at: string | null;
  resolved_by: string | null;
  created_at: string | null;
}

interface AdminUserRow {
  id: string;
  username: string;
}

const STATUS_FILTERS = [
  { value: "open-or-acknowledged", label: "Open + acknowledged" },
  { value: "open", label: "Open" },
  { value: "acknowledged", label: "Acknowledged" },
  { value: "resolved", label: "Resolved" },
  { value: "dismissed", label: "Dismissed" },
  { value: "", label: "All" },
];

const CATEGORY_LABELS: Record<string, string> = {
  incorrect_info: "Incorrect info",
  vision_wrong: "Vision wrong",
  tool_error: "Tool error",
  slow: "Slow",
  ui_bug: "UI bug",
  other: "Other",
};

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  open: { bg: "bg-amber-500/15", text: "text-amber-300" },
  acknowledged: { bg: "bg-sky-500/15", text: "text-sky-300" },
  resolved: { bg: "bg-emerald-500/15", text: "text-emerald-300" },
  dismissed: { bg: "bg-gray-500/15", text: "text-gray-400" },
};

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

  return (
    <div className="max-w-6xl">
      <h2 className="text-xl font-semibold mb-4">Bug reports</h2>

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

      <div className="border border-[#2a2a2c] rounded overflow-hidden">
        <table className="w-full text-sm">
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
                  No bug reports match the current filters.
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
                  {b.created_at
                    ? new Date(b.created_at).toLocaleString()
                    : "—"}
                </td>
                <td className="px-3 py-2">{b.user_display_name}</td>
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

function StatusBadge({ status }: { status: string }) {
  const c = STATUS_COLORS[status] ?? {
    bg: "bg-gray-500/15",
    text: "text-gray-300",
  };
  return (
    <span
      className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wide ${c.bg} ${c.text}`}
    >
      {status}
    </span>
  );
}

function BugDetailModal({
  bug,
  onClose,
  onChanged,
}: {
  bug: AdminBugReport;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const callAction = async (action: "acknowledge" | "resolve" | "dismiss") => {
    setBusy(true);
    setError(null);
    try {
      const r = await apiFetch(`/api/admin/bug-reports/${bug.id}/${action}`, {
        method: "POST",
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
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const deleteRow = async () => {
    if (!window.confirm("Delete this bug report? Cannot be undone.")) return;
    setBusy(true);
    setError(null);
    try {
      const r = await apiFetch(`/api/admin/bug-reports/${bug.id}`, {
        method: "DELETE",
      });
      if (!r.ok) {
        setError(`Delete failed (${r.status})`);
        return;
      }
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="bg-[#1e1e1f] text-[#e3e3e3] rounded-lg w-full max-w-2xl max-h-[80vh] overflow-hidden flex flex-col border border-[#2a2a2c]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-[#2a2a2c]">
          <div className="flex items-center gap-3">
            <h3 className="text-sm font-semibold">Bug report</h3>
            <StatusBadge status={bug.status} />
          </div>
          <button
            type="button"
            className="text-gray-400 hover:text-[#e3e3e3] text-lg leading-none"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="overflow-y-auto custom-scrollbar p-5 space-y-4 text-sm">
          <DetailRow
            label="Category"
            value={CATEGORY_LABELS[bug.category] ?? bug.category}
          />
          <DetailRow label="Reporter" value={bug.user_display_name} />
          <DetailRow
            label="When"
            value={
              bug.created_at
                ? new Date(bug.created_at).toLocaleString()
                : "—"
            }
          />
          <DetailRow label="Workspace" value={bug.workspace_id ?? "—"} mono />
          <div className="flex gap-4">
            <div className="text-xs text-gray-400 w-24 shrink-0 pt-0.5">
              Session
            </div>
            <div className="flex-1 font-mono text-xs">
              {bug.session_id ? (
                <Link
                  href={`/admin/sessions/${encodeURIComponent(bug.session_id)}`}
                  className="text-sky-400 hover:underline"
                >
                  Read session →
                </Link>
              ) : (
                "—"
              )}
            </div>
          </div>
          {bug.resolved_at && (
            <DetailRow
              label="Resolved"
              value={new Date(bug.resolved_at).toLocaleString()}
            />
          )}

          <div>
            <div className="text-xs text-gray-400 mb-1">Message</div>
            <div className="bg-[#131314] border border-[#2a2a2c] rounded p-3 text-sm whitespace-pre-wrap">
              {bug.message}
            </div>
          </div>

          {bug.payload && Object.keys(bug.payload).length > 0 && (
            <div>
              <div className="text-xs text-gray-400 mb-1">Context</div>
              <pre className="bg-[#131314] border border-[#2a2a2c] rounded p-3 text-xs overflow-x-auto custom-scrollbar">
                {JSON.stringify(bug.payload, null, 2)}
              </pre>
            </div>
          )}

          {error && <div className="text-sm text-red-400">{error}</div>}
        </div>

        <div className="flex gap-2 px-5 py-3 border-t border-[#2a2a2c] justify-end flex-wrap">
          <button
            type="button"
            onClick={deleteRow}
            disabled={busy}
            className="text-sm px-3 py-1.5 rounded bg-red-500/15 border border-red-500/30 text-red-300 hover:bg-red-500/25 disabled:opacity-50"
          >
            Delete
          </button>
          <button
            type="button"
            onClick={() => callAction("dismiss")}
            disabled={busy || bug.status === "dismissed"}
            className="text-sm px-3 py-1.5 rounded bg-[#1e1e1f] border border-[#2a2a2c] hover:bg-[#2a2a2c] disabled:opacity-50"
          >
            Dismiss
          </button>
          <button
            type="button"
            onClick={() => callAction("acknowledge")}
            disabled={busy || bug.status === "acknowledged" || bug.status === "resolved"}
            className="text-sm px-3 py-1.5 rounded bg-sky-500/15 border border-sky-500/30 text-sky-300 hover:bg-sky-500/25 disabled:opacity-50"
          >
            Acknowledge
          </button>
          <button
            type="button"
            onClick={() => callAction("resolve")}
            disabled={busy || bug.status === "resolved"}
            className="text-sm px-3 py-1.5 rounded bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/25 disabled:opacity-50"
          >
            Resolve + notify
          </button>
        </div>
      </div>
    </div>
  );
}

function DetailRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex gap-4">
      <div className="text-xs text-gray-400 w-24 shrink-0 pt-0.5">{label}</div>
      <div className={(mono ? "font-mono text-xs " : "") + "flex-1"}>
        {value}
      </div>
    </div>
  );
}
