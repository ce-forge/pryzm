"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/utils/apiClient";
import { EventTypeBadge } from "./EventTypeBadge";

export interface AuditEventDetail {
  id: string;
  user_id: string | null;
  user_display_name_at_event: string | null;
  event_type: string;
  workspace_id: string | null;
  workspace_display_name: string | null;
  session_id: string | null;
  session_title: string | null;
  resource_type: string | null;
  resource_id: string | null;
  payload: Record<string, unknown>;
  source_ip: string | null;
  user_agent: string | null;
  created_at: string | null;
}

interface Props {
  eventId: string;
  onClose: () => void;
}

export function AuditEventDetailModal({ eventId, onClose }: Props) {
  const [event, setEvent] = useState<AuditEventDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch(`/api/admin/audit/${encodeURIComponent(eventId)}`)
      .then(async (r) => {
        if (cancelled) return;
        if (!r.ok) {
          setError(`Failed to load event (${r.status})`);
          return;
        }
        setEvent(await r.json());
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [eventId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
    >
      <div
        className="bg-[#1e1e1f] text-[#e3e3e3] rounded-lg w-full max-w-2xl max-h-[80vh] overflow-hidden flex flex-col border border-[#2a2a2c]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-[#2a2a2c]">
          <h3 className="text-sm font-semibold">Audit event</h3>
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
          {error && <div className="text-red-400">{error}</div>}
          {!event && !error && <div className="text-gray-400">Loading…</div>}
          {event && (
            <>
              <div className="flex gap-4 items-center">
                <div className="text-xs text-gray-400 w-24 shrink-0">
                  Event type
                </div>
                <EventTypeBadge eventType={event.event_type} />
              </div>
              <DetailRow
                label="When"
                value={
                  event.created_at
                    ? new Date(event.created_at).toLocaleString()
                    : "—"
                }
              />
              <DetailRow
                label="User"
                value={
                  event.user_display_name_at_event
                    ? `${event.user_display_name_at_event}${
                        event.user_id ? "" : " (deleted)"
                      }`
                    : "—"
                }
              />
              <NamedIdRow
                label="Workspace"
                id={event.workspace_id}
                name={event.workspace_display_name}
              />
              <NamedIdRow
                label="Session"
                id={event.session_id}
                name={event.session_title}
                href={
                  event.session_id
                    ? `/admin/sessions/${encodeURIComponent(event.session_id)}`
                    : null
                }
              />
              <DetailRow
                label="Resource"
                value={
                  event.resource_type
                    ? `${event.resource_type}: ${event.resource_id ?? "—"}`
                    : "—"
                }
                mono
              />
              <DetailRow label="Source IP" value={event.source_ip ?? "—"} mono />
              <DetailRow
                label="User agent"
                value={event.user_agent ?? "—"}
                mono
                wrap
              />
              <div>
                <div className="text-xs text-gray-400 mb-1">Payload</div>
                <pre className="bg-[#131314] border border-[#2a2a2c] rounded p-3 text-xs overflow-x-auto custom-scrollbar">
                  {JSON.stringify(event.payload, null, 2)}
                </pre>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function DetailRow({
  label,
  value,
  mono,
  wrap,
}: {
  label: string;
  value: string;
  mono?: boolean;
  wrap?: boolean;
}) {
  return (
    <div className="flex gap-4">
      <div className="text-xs text-gray-400 w-24 shrink-0 pt-0.5">{label}</div>
      <div
        className={
          (mono ? "font-mono text-xs " : "") +
          (wrap ? "break-all " : "") +
          "flex-1"
        }
      >
        {value}
      </div>
    </div>
  );
}

/**
 * Renders an entity reference as "display_name" on top and "<uuid>" muted
 * underneath. Falls back to "(deleted)" when only the id is null (FK was
 * SET NULL on cascade) or just the raw id when the name didn't resolve.
 */
function NamedIdRow({
  label,
  id,
  name,
  href,
}: {
  label: string;
  id: string | null;
  name: string | null;
  href?: string | null;
}) {
  const display = name ?? (id ? <span className="text-gray-500">(unknown)</span> : null);
  return (
    <div className="flex gap-4">
      <div className="text-xs text-gray-400 w-24 shrink-0 pt-0.5">{label}</div>
      <div className="flex-1 min-w-0">
        {id ? (
          <>
            <div className="text-sm truncate">
              {href ? (
                <Link
                  href={href}
                  className="text-sky-400 hover:underline"
                >
                  {display}
                </Link>
              ) : (
                display
              )}
            </div>
            <div className="font-mono text-[10px] text-gray-500 truncate">
              {id}
            </div>
          </>
        ) : (
          <span className="text-gray-500">—</span>
        )}
      </div>
    </div>
  );
}
