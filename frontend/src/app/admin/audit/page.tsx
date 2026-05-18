"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "@/utils/apiClient";
import { AuditEventDetailModal } from "@/components/admin/AuditEventDetailModal";
import { EventTypeBadge } from "@/components/admin/EventTypeBadge";

interface AuditEvent {
  id: string;
  user_id: string | null;
  user_display_name_at_event: string | null;
  event_type: string;
  workspace_id: string | null;
  session_id: string | null;
  resource_type: string | null;
  resource_id: string | null;
  payload: Record<string, unknown>;
  created_at: string | null;
}

interface AdminUserRow {
  id: string;
  username: string;
}

const TIME_PRESETS = [
  { label: "All time", hours: null },
  { label: "Last hour", hours: 1 },
  { label: "Last day", hours: 24 },
  { label: "Last week", hours: 24 * 7 },
  { label: "Last month", hours: 24 * 30 },
];

const PAGE_SIZE = 50;

export default function AdminAuditPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);

  // Filters
  const [eventTypeFilter, setEventTypeFilter] = useState<string>("");
  const [userFilter, setUserFilter] = useState<string>("");
  const [timePresetHours, setTimePresetHours] = useState<number | null>(null);

  // Dropdown sources
  const [eventTypes, setEventTypes] = useState<string[]>([]);
  const [users, setUsers] = useState<AdminUserRow[]>([]);

  // Cancellation: bump on every fresh load so an in-flight request from a
  // previous filter doesn't overwrite the current results when it returns.
  const reqIdRef = useRef(0);

  const buildQuery = useCallback(
    (cursor: string | null) => {
      const params = new URLSearchParams();
      params.set("limit", String(PAGE_SIZE));
      if (cursor) params.set("cursor", cursor);
      if (eventTypeFilter) params.set("event_type", eventTypeFilter);
      if (userFilter) params.set("user_id", userFilter);
      if (timePresetHours !== null) {
        const from = new Date(Date.now() - timePresetHours * 3600 * 1000);
        params.set("from", from.toISOString());
      }
      return params.toString();
    },
    [eventTypeFilter, userFilter, timePresetHours]
  );

  const loadFirstPage = useCallback(async () => {
    const myReqId = ++reqIdRef.current;
    setLoading(true);
    setError(null);
    try {
      const r = await apiFetch(`/api/admin/audit?${buildQuery(null)}`);
      if (myReqId !== reqIdRef.current) return;
      if (!r.ok) {
        setError(`Failed to load (${r.status})`);
        return;
      }
      const body = await r.json();
      setEvents(body.events);
      setNextCursor(body.next_cursor);
    } catch (e) {
      if (myReqId === reqIdRef.current) setError(String(e));
    } finally {
      if (myReqId === reqIdRef.current) setLoading(false);
    }
  }, [buildQuery]);

  const loadMore = useCallback(async () => {
    if (!nextCursor || loading) return;
    const myReqId = ++reqIdRef.current;
    setLoading(true);
    try {
      const r = await apiFetch(`/api/admin/audit?${buildQuery(nextCursor)}`);
      if (myReqId !== reqIdRef.current) return;
      if (!r.ok) {
        setError(`Failed to load (${r.status})`);
        return;
      }
      const body = await r.json();
      setEvents((prev) => [...prev, ...body.events]);
      setNextCursor(body.next_cursor);
    } catch (e) {
      if (myReqId === reqIdRef.current) setError(String(e));
    } finally {
      if (myReqId === reqIdRef.current) setLoading(false);
    }
  }, [buildQuery, nextCursor, loading]);

  // Initial + filter-change load. loadFirstPage updates state internally;
  // that's the whole point — refetch and replace results whenever the
  // filter set changes. eslint's set-state-in-effect rule doesn't model
  // async-fetch effects.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadFirstPage();
  }, [loadFirstPage]);

  // Dropdown source loads (once)
  useEffect(() => {
    apiFetch("/api/admin/audit/event-types")
      .then((r) => (r.ok ? r.json() : { event_types: [] }))
      .then((body) => setEventTypes(body.event_types || []));
    apiFetch("/api/admin/users")
      .then((r) => (r.ok ? r.json() : []))
      .then((body) => setUsers(Array.isArray(body) ? body : []));
  }, []);

  // Group event types by domain prefix for the dropdown.
  const eventTypeOptions = useMemo(() => {
    const groups: Record<string, string[]> = {};
    for (const et of eventTypes) {
      const [prefix] = et.split(".");
      (groups[prefix] ||= []).push(et);
    }
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
  }, [eventTypes]);

  return (
    <div className="max-w-6xl">
      <h2 className="text-xl font-semibold mb-4">Audit</h2>

      <div className="flex flex-wrap gap-3 items-end mb-4">
        <FilterColumn label="Event type">
          <select
            value={eventTypeFilter}
            onChange={(e) => setEventTypeFilter(e.target.value)}
            className="bg-[#1e1e1f] border border-[#2a2a2c] rounded px-2 py-1.5 text-sm min-w-56"
          >
            <option value="">All types</option>
            {eventTypeOptions.map(([prefix, types]) => (
              <optgroup key={prefix} label={prefix}>
                <option value={`prefix:${prefix}`}>{`All ${prefix}.*`}</option>
                {types.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </FilterColumn>

        <FilterColumn label="User">
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

        <FilterColumn label="Time range">
          <div className="flex gap-1">
            {TIME_PRESETS.map((p) => {
              const active = timePresetHours === p.hours;
              return (
                <button
                  key={p.label}
                  type="button"
                  onClick={() => setTimePresetHours(p.hours)}
                  className={
                    "px-2.5 py-1.5 text-xs rounded border " +
                    (active
                      ? "bg-[#2a2a2c] border-[#3a3a3c] text-[#e3e3e3]"
                      : "border-[#2a2a2c] text-gray-400 hover:text-[#e3e3e3]")
                  }
                >
                  {p.label}
                </button>
              );
            })}
          </div>
        </FilterColumn>
      </div>

      {error && (
        <div className="mb-3 text-sm text-red-400">{error}</div>
      )}

      <div className="border border-[#2a2a2c] rounded overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-[#1e1e1f] text-xs text-gray-400 text-left">
            <tr>
              <th className="px-3 py-2 font-medium w-40">When</th>
              <th className="px-3 py-2 font-medium w-32">User</th>
              <th className="px-3 py-2 font-medium w-64">Event</th>
              <th className="px-3 py-2 font-medium">Payload preview</th>
            </tr>
          </thead>
          <tbody>
            {events.length === 0 && !loading && (
              <tr>
                <td colSpan={4} className="px-3 py-6 text-center text-gray-500">
                  No events match the current filters.
                </td>
              </tr>
            )}
            {events.map((e) => (
              <tr
                key={e.id}
                onClick={() => setSelectedEventId(e.id)}
                className="border-t border-[#2a2a2c] hover:bg-[#1a1a1b] cursor-pointer"
              >
                <td className="px-3 py-2 text-gray-400 whitespace-nowrap text-xs">
                  {e.created_at
                    ? new Date(e.created_at).toLocaleString()
                    : "—"}
                </td>
                <td className="px-3 py-2 truncate max-w-32">
                  {e.user_display_name_at_event ?? (
                    <span className="text-gray-500">system</span>
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

      <div className="mt-4 flex items-center justify-between">
        <div className="text-xs text-gray-500">
          {events.length} {events.length === 1 ? "event" : "events"} loaded
        </div>
        {nextCursor && (
          <button
            type="button"
            onClick={loadMore}
            disabled={loading}
            className="text-sm px-3 py-1.5 rounded bg-[#1e1e1f] border border-[#2a2a2c] hover:bg-[#2a2a2c] disabled:opacity-50"
          >
            {loading ? "Loading…" : "Load more"}
          </button>
        )}
      </div>

      {selectedEventId && (
        <AuditEventDetailModal
          eventId={selectedEventId}
          onClose={() => setSelectedEventId(null)}
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

function payloadSummary(payload: Record<string, unknown>): string {
  if (!payload || Object.keys(payload).length === 0) return "—";
  if (payload._truncated && typeof payload._preview === "string") {
    return payload._preview;
  }
  // Compact JSON, trimmed.
  const s = JSON.stringify(payload);
  return s.length > 140 ? s.slice(0, 140) + "…" : s;
}
