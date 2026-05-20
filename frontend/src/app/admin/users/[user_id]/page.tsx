"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { apiFetch } from "@/utils/apiClient";
import { EventTypeBadge } from "@/components/admin/EventTypeBadge";
import Identicon from "@/components/Identicon";

interface AdminUser {
  id: string;
  username: string;
  email: string | null;
  is_admin: boolean;
  is_active: boolean;
  can_create_workspaces: boolean;
  allowed_tools: string[];
  created_at: string | null;
  last_login_at: string | null;
}

interface AdminWorkspace {
  id: string;
  slug: string;
  display_name: string;
  template_id: string | null;
  owner_can_edit: boolean;
  enabled_tools: string[];
}

interface AuditRow {
  id: string;
  event_type: string;
  created_at: string | null;
  payload: Record<string, unknown>;
}

interface AdminBugReport {
  id: string;
  category: string;
  status: string;
  message: string;
  created_at: string | null;
}

const RECENT_ACTIVITY_LIMIT = 20;

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  open: { bg: "bg-amber-500/15", text: "text-amber-300" },
  acknowledged: { bg: "bg-sky-500/15", text: "text-sky-300" },
  resolved: { bg: "bg-emerald-500/15", text: "text-emerald-300" },
  dismissed: { bg: "bg-gray-500/15", text: "text-gray-400" },
};

export default function AdminUserDetailPage() {
  const params = useParams<{ user_id: string }>();
  const userId = params.user_id;

  const [user, setUser] = useState<AdminUser | null>(null);
  const [workspaces, setWorkspaces] = useState<AdminWorkspace[]>([]);
  const [activity, setActivity] = useState<AuditRow[]>([]);
  const [bugs, setBugs] = useState<AdminBugReport[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError(null);
    try {
      const [uRes, wRes, aRes, bRes] = await Promise.all([
        apiFetch(`/api/admin/users/${encodeURIComponent(userId)}`),
        apiFetch(`/api/admin/users/${encodeURIComponent(userId)}/workspaces`),
        apiFetch(
          `/api/admin/audit?user_id=${encodeURIComponent(userId)}&limit=${RECENT_ACTIVITY_LIMIT}`,
        ),
        apiFetch(`/api/admin/bug-reports?user_id=${encodeURIComponent(userId)}`),
      ]);

      if (uRes.status === 404) {
        setError("User not found.");
        return;
      }
      if (!uRes.ok) {
        setError(`Failed to load user (${uRes.status})`);
        return;
      }
      setUser(await uRes.json());
      setWorkspaces(wRes.ok ? await wRes.json() : []);
      const auditBody = aRes.ok ? await aRes.json() : { events: [] };
      setActivity(auditBody.events ?? []);
      setBugs(bRes.ok ? await bRes.json() : []);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  if (loading) {
    return <div className="text-sm text-gray-400">Loading…</div>;
  }
  if (error) {
    return <div className="text-sm text-red-400">{error}</div>;
  }
  if (!user) {
    return null;
  }

  const openBugs = bugs.filter(
    (b) => b.status === "open" || b.status === "acknowledged",
  );

  return (
    <div className="max-w-5xl space-y-8">
      <div>
        <Link
          href="/admin/users"
          className="text-xs text-gray-400 hover:text-[#e3e3e3]"
        >
          ← All users
        </Link>
        <h2 className="text-xl font-semibold mt-2 flex items-center gap-3">
          <Identicon seed={user.username} size={32} />
          {user.username}
        </h2>
        <div className="text-xs text-gray-400 mt-1 flex flex-wrap gap-3">
          <FlagPill label="Admin" on={user.is_admin} />
          <FlagPill label="Active" on={user.is_active} />
          <FlagPill
            label="Can create workspaces"
            on={user.can_create_workspaces}
          />
          {user.email && <span>{user.email}</span>}
          {user.last_login_at && (
            <span>
              Last login: {new Date(user.last_login_at).toLocaleString()}
            </span>
          )}
          <span>
            Tools:{" "}
            {user.allowed_tools.length === 0 ? (
              <span className="text-gray-500">no restriction</span>
            ) : (
              <code className="font-mono">{user.allowed_tools.join(", ")}</code>
            )}
          </span>
        </div>
      </div>

      {/* Workspaces */}
      <section>
        <SectionHeading
          title="Workspaces"
          subtitle={`${workspaces.length} owned`}
        />
        {workspaces.length === 0 ? (
          <EmptyHint>This user has no workspaces.</EmptyHint>
        ) : (
          <div className="border border-[#2a2a2c] rounded overflow-x-auto">
            <table className="w-full text-sm min-w-[600px]">
              <thead className="bg-[#1e1e1f] text-xs text-gray-400 text-left">
                <tr>
                  <th className="px-3 py-2 font-medium max-md:sticky max-md:left-0 max-md:bg-[#1e1e1f]">Name</th>
                  <th className="px-3 py-2 font-medium w-32">Slug</th>
                  <th className="px-3 py-2 font-medium w-28">Owner edits</th>
                  <th className="px-3 py-2 font-medium w-40">Template</th>
                </tr>
              </thead>
              <tbody>
                {workspaces.map((w) => {
                  const violations =
                    !user.is_admin && user.allowed_tools.length > 0
                      ? w.enabled_tools.filter(
                          (t) => !user.allowed_tools.includes(t),
                        )
                      : [];
                  return (
                    <React.Fragment key={w.id}>
                      <tr className="border-t border-[#2a2a2c]">
                        <td className="px-3 py-2 max-md:sticky max-md:left-0 max-md:bg-[#131314]">{w.display_name}</td>
                        <td className="px-3 py-2 font-mono text-xs text-gray-400">
                          {w.slug}
                        </td>
                        <td className="px-3 py-2 text-xs text-gray-300">
                          {w.owner_can_edit ? "yes" : "no"}
                        </td>
                        <td className="px-3 py-2 text-xs text-gray-400 font-mono truncate">
                          {w.template_id ?? "—"}
                        </td>
                      </tr>
                      {violations.length > 0 && (
                        <tr className="border-t border-[#2a2a2c]">
                          <td
                            colSpan={4}
                            className="px-3 py-1 text-xs text-amber-400"
                          >
                            Grandfathered:{" "}
                            <code className="font-mono">
                              {violations.join(", ")}
                            </code>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="mt-2 text-xs text-gray-500">
          Use the{" "}
          <Link
            href="/admin/workspaces"
            className="text-sky-400 hover:underline"
          >
            workspaces tab
          </Link>{" "}
          for edit / delete / toggle owner-edit.
        </div>
      </section>

      {/* Open alerts */}
      <section>
        <SectionHeading
          title="Open alerts"
          subtitle={`${openBugs.length} open or acknowledged of ${bugs.length} total`}
        />
        {openBugs.length === 0 ? (
          <EmptyHint>No open alerts from this user.</EmptyHint>
        ) : (
          <div className="border border-[#2a2a2c] rounded overflow-x-auto">
            <table className="w-full text-sm min-w-[600px]">
              <thead className="bg-[#1e1e1f] text-xs text-gray-400 text-left">
                <tr>
                  <th className="px-3 py-2 font-medium w-40">When</th>
                  <th className="px-3 py-2 font-medium w-24">Status</th>
                  <th className="px-3 py-2 font-medium w-32">Category</th>
                  <th className="px-3 py-2 font-medium">Message</th>
                </tr>
              </thead>
              <tbody>
                {openBugs.map((b) => (
                  <tr key={b.id} className="border-t border-[#2a2a2c]">
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
                      <StatusBadge status={b.status} />
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-300">
                      {b.category}
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
        )}
        <div className="mt-2 text-xs text-gray-500">
          Full triage on the{" "}
          <Link
            href="/admin/bug-reports"
            className="text-sky-400 hover:underline"
          >
            alerts tab
          </Link>
          .
        </div>
      </section>

      {/* Recent activity (audit) */}
      <section>
        <SectionHeading
          title="Recent activity"
          subtitle={`Last ${activity.length} audit events`}
        />
        {activity.length === 0 ? (
          <EmptyHint>No audit events yet for this user.</EmptyHint>
        ) : (
          <div className="border border-[#2a2a2c] rounded overflow-x-auto">
            <table className="w-full text-sm min-w-[600px]">
              <thead className="bg-[#1e1e1f] text-xs text-gray-400 text-left">
                <tr>
                  <th className="px-3 py-2 font-medium w-40">When</th>
                  <th className="px-3 py-2 font-medium w-64">Event</th>
                  <th className="px-3 py-2 font-medium">Payload preview</th>
                </tr>
              </thead>
              <tbody>
                {activity.map((e) => (
                  <tr key={e.id} className="border-t border-[#2a2a2c]">
                    <td className="px-3 py-2 text-xs text-gray-400 whitespace-nowrap">
                      {e.created_at ? (
                        <>
                          <div>{new Date(e.created_at).toLocaleDateString()}</div>
                          <div>{new Date(e.created_at).toLocaleTimeString()}</div>
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-3 py-2 truncate max-w-64">
                      <EventTypeBadge eventType={e.event_type} />
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-400 truncate">
                      {payloadSummary(e.payload)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="mt-2 text-xs text-gray-500">
          Drill in via the{" "}
          <Link
            href={`/admin/audit?user_id=${encodeURIComponent(user.id)}`}
            className="text-sky-400 hover:underline"
          >
            audit tab
          </Link>
          .
        </div>
      </section>
    </div>
  );
}

function SectionHeading({
  title,
  subtitle,
}: {
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="flex items-baseline gap-3 mb-3">
      <h3 className="text-sm font-semibold text-gray-200">{title}</h3>
      {subtitle && <span className="text-xs text-gray-500">{subtitle}</span>}
    </div>
  );
}

function FlagPill({ label, on }: { label: string; on: boolean }) {
  return (
    <span
      className={
        "inline-block px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wide " +
        (on
          ? "bg-emerald-500/15 text-emerald-300"
          : "bg-gray-500/15 text-gray-500")
      }
    >
      {label}: {on ? "yes" : "no"}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const c =
    STATUS_COLORS[status] ?? { bg: "bg-gray-500/15", text: "text-gray-300" };
  return (
    <span
      className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wide ${c.bg} ${c.text}`}
    >
      {status}
    </span>
  );
}

function EmptyHint({ children }: { children: React.ReactNode }) {
  return (
    <div className="border border-[#2a2a2c] rounded px-4 py-6 text-center text-xs text-gray-500">
      {children}
    </div>
  );
}

function payloadSummary(payload: Record<string, unknown>): string {
  if (!payload || Object.keys(payload).length === 0) return "—";
  if (payload._truncated && typeof payload._preview === "string") {
    return payload._preview;
  }
  const s = JSON.stringify(payload);
  return s.length > 140 ? s.slice(0, 140) + "…" : s;
}
