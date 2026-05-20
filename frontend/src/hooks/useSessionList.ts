"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/utils/apiClient";
import { withRollback } from "@/utils/withRollback";
import { isOptimisticSessionId } from "@/utils/ids";

export interface SessionInfo {
  id: string;
  title: string;
  folder_id?: string | null;
  is_pinned?: boolean;
}

interface Options {
  workspace: string;
  currentSessionId: string | null;
  subscribeSessionCreated: (fn: () => void) => () => void;
}

/**
 * Owns the sessions list for the active workspace: fetch, optimistic-id
 * reconciliation when the URL flips to a real session id, and the move-to-
 * folder mutation. SessionDirectory consumes this; SessionItem still owns
 * its own per-row mutations through `setSessions`.
 */
export function useSessionList({
  workspace,
  currentSessionId,
  subscribeSessionCreated,
}: Options) {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);

  const fetchSessions = useCallback(() => {
    apiFetch(`/sessions?workspace=${workspace}`, { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!Array.isArray(data)) return;
        setSessions((prev) => {
          const backendHasActive = data.some((s: SessionInfo) => s.id === currentSessionId);
          if (
            currentSessionId &&
            currentSessionId !== "temp_new_chat" &&
            !backendHasActive
          ) {
            const existingOptimistic = prev.find((s) => s.id === currentSessionId);
            const placeholder =
              existingOptimistic || { id: currentSessionId, title: "", is_pinned: false };
            return [placeholder, ...data];
          }
          return data;
        });
      })
      .catch((err) => console.error("Error loading sessions:", err));
  }, [workspace, currentSessionId]);

  useEffect(() => {
    fetchSessions();
    return subscribeSessionCreated(fetchSessions);
  }, [fetchSessions, subscribeSessionCreated]);

  // Anti-flicker: when the URL drops a real session id, swap any matching
  // optimistic row out of the local list.
  useEffect(() => {
    if (currentSessionId && currentSessionId !== "temp_new_chat") {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSessions((prev) => {
        if (!prev.some((s) => s.id === currentSessionId)) {
          const optimisticItem = prev.find((s) => isOptimisticSessionId(s.id));
          const titleToUse = optimisticItem?.title || "";
          const cleaned = prev.filter((s) => !isOptimisticSessionId(s.id));
          return [{ id: currentSessionId, title: titleToUse, is_pinned: false }, ...cleaned];
        }
        return prev;
      });
    }
  }, [currentSessionId]);

  const moveSessionToFolder = useCallback(
    async (sessionId: string, folderId: string | null) => {
      const previous = sessions.find((s) => s.id === sessionId);
      const previousFolderId = previous?.folder_id ?? null;
      if (previousFolderId === folderId) return;

      try {
        await withRollback(
          () =>
            setSessions((prev) =>
              prev.map((s) => (s.id === sessionId ? { ...s, folder_id: folderId } : s)),
            ),
          () =>
            setSessions((prev) =>
              prev.map((s) =>
                s.id === sessionId ? { ...s, folder_id: previousFolderId } : s,
              ),
            ),
          async () => {
            const r = await apiFetch(`/sessions/${sessionId}?workspace=${workspace}`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ folder_id: folderId }),
            });
            if (!r.ok) throw new Error("move failed");
          },
        );
      } catch (err) {
        console.error("Session move failed", err);
      }
    },
    [sessions, workspace],
  );

  return { sessions, setSessions, fetchSessions, moveSessionToFolder };
}
