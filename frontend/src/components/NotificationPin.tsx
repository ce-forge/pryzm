"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/utils/apiClient";

interface Notification {
  id: string;
  message: string;
  source: string;
  source_id: string | null;
  link_url: string | null;
  created_at: string | null;
  seen_at: string | null;
}

const POLL_INTERVAL_MS = 30_000;
const POPOVER_AUTOCLOSE_MS = 5_000;


function BellIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </svg>
  );
}

// Sidebar uses a translate transform for its slide animation, which makes
// it the containing block for any `position: fixed` descendant. We can't
// position the popover relative to the viewport from inside it; the
// portal escapes that constraint.
const POPOVER_WIDTH = 320;
const POPOVER_MARGIN = 8;

export function NotificationPin() {
  const router = useRouter();
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const autoCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Wait for client mount before using createPortal (document is undefined
  // during the server render).
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMounted(true);
  }, []);

  // Compute popover position from the bell's viewport rect. Right-aligned
  // to the bell when there's space; clamped to viewport edges otherwise.
  const recalcPosition = useCallback(() => {
    const el = buttonRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const idealLeft = rect.right - POPOVER_WIDTH;
    const minLeft = POPOVER_MARGIN;
    const maxLeft = window.innerWidth - POPOVER_WIDTH - POPOVER_MARGIN;
    const left = Math.min(Math.max(idealLeft, minLeft), maxLeft);
    const top = rect.bottom + 4;
    setPosition({ top, left });
  }, []);

  useEffect(() => {
    if (!open) return;
    recalcPosition();
    const onResize = () => recalcPosition();
    window.addEventListener("resize", onResize);
    window.addEventListener("scroll", onResize, true);
    return () => {
      window.removeEventListener("resize", onResize);
      window.removeEventListener("scroll", onResize, true);
    };
  }, [open, recalcPosition]);

  const refresh = useCallback(async () => {
    try {
      const r = await apiFetch("/api/notifications/unseen");
      if (!r.ok) return;
      const body = await r.json();
      setNotifications(body.notifications ?? []);
    } catch {
      // Polling failures are silent — the bell just won't update.
    }
  }, []);

  // Mount → fetch once + start polling. Re-fetch on window focus so
  // returning from a stale tab catches up immediately.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
    const interval = setInterval(refresh, POLL_INTERVAL_MS);
    const onFocus = () => refresh();
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", onFocus);
    };
  }, [refresh]);

  // Click-outside + Escape close the popover. Popover is portal-rendered
  // so contains-checks must consider the button AND the popover.
  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      const target = e.target as Node;
      const insidePopover =
        popoverRef.current && popoverRef.current.contains(target);
      const insideButton =
        buttonRef.current && buttonRef.current.contains(target);
      if (!insidePopover && !insideButton) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // Auto-close after a quiet interval inside the popover. Resets whenever
  // the user interacts (mousemove/scroll within the popover).
  const resetAutoClose = useCallback(() => {
    if (autoCloseTimerRef.current) clearTimeout(autoCloseTimerRef.current);
    autoCloseTimerRef.current = setTimeout(() => setOpen(false), POPOVER_AUTOCLOSE_MS);
  }, []);

  useEffect(() => {
    if (!open) {
      if (autoCloseTimerRef.current) {
        clearTimeout(autoCloseTimerRef.current);
        autoCloseTimerRef.current = null;
      }
      return;
    }
    resetAutoClose();
    return () => {
      if (autoCloseTimerRef.current) clearTimeout(autoCloseTimerRef.current);
    };
  }, [open, resetAutoClose]);

  const markSeen = async (n: Notification) => {
    setNotifications((prev) => prev.filter((x) => x.id !== n.id));
    try {
      await apiFetch(`/api/notifications/${n.id}/seen`, { method: "POST" });
    } catch {
      // If the call fails we leak the optimistic remove until the next
      // poll. Acceptable — the row eventually reconciles.
    }
  };

  const markAllSeen = async () => {
    setNotifications([]);
    try {
      await apiFetch("/api/notifications/seen-all", { method: "POST" });
    } catch {
      // Same trade-off as markSeen.
    }
  };

  const onClickRow = (n: Notification) => {
    markSeen(n);
    if (n.link_url) {
      // Internal paths go through the router (no full reload); external
      // URLs would need window.location, but we don't ship those today.
      router.push(n.link_url);
      setOpen(false);
    }
  };

  const unseen = notifications.length;

  const popover = open && position && (
    <div
      ref={popoverRef}
      onMouseMove={resetAutoClose}
      style={{
        position: "fixed",
        top: position.top,
        left: position.left,
        width: POPOVER_WIDTH,
        zIndex: 1000,
      }}
      className="bg-[#1e1e1f] border border-[#2a2a2c] rounded-lg shadow-2xl overflow-hidden"
    >
      <div className="px-4 py-2 border-b border-[#2a2a2c] flex items-center justify-between">
        <span className="text-xs font-semibold text-gray-300">
          {unseen > 0 ? `${unseen} new` : "All caught up"}
        </span>
        {unseen > 0 && (
          <button
            type="button"
            onClick={markAllSeen}
            className="text-[11px] text-gray-400 hover:text-[#e3e3e3]"
          >
            Mark all as seen
          </button>
        )}
      </div>

      <div className="max-h-80 overflow-y-auto custom-scrollbar">
        {unseen === 0 ? (
          <div className="px-4 py-6 text-center text-xs text-gray-500">
            Nothing new.
          </div>
        ) : (
          notifications.map((n) => (
            <div
              key={n.id}
              className="flex items-start gap-2 px-4 py-2.5 hover:bg-[#282a2c] cursor-pointer border-b border-[#2a2a2c] last:border-b-0"
              onClick={() => onClickRow(n)}
            >
              <div className="flex-1 min-w-0">
                <div className="text-sm text-[#e3e3e3] break-words">
                  {n.message}
                </div>
                {n.created_at && (
                  <div className="text-[10px] text-gray-500 mt-0.5">
                    {new Date(n.created_at).toLocaleString()}
                  </div>
                )}
              </div>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  markSeen(n);
                }}
                className="text-gray-500 hover:text-[#e3e3e3] text-xs leading-none shrink-0"
                aria-label="Dismiss notification"
                title="Dismiss"
              >
                ×
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="relative p-1.5 rounded text-gray-400 hover:text-[#e3e3e3] hover:bg-[#282a2c] transition-colors"
        title={unseen > 0 ? `${unseen} unseen notification${unseen === 1 ? "" : "s"}` : "Notifications"}
        aria-label="Notifications"
      >
        <BellIcon className="w-4 h-4" />
        {unseen > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-white text-[10px] font-medium leading-4 text-center">
            {unseen > 9 ? "9+" : unseen}
          </span>
        )}
      </button>
      {mounted && popover ? createPortal(popover, document.body) : null}
    </>
  );
}
