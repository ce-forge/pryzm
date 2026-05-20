"use client";

import React, { useCallback, useMemo, useRef } from "react";
import { useSession } from "@/hooks/useSession";
import { Message, ReferencedFile, ToolCall } from "@/types/chat";
import {
  SessionMetaContext,
  type SessionMetaContextValue,
  useSessionMetaContext,
} from "@/context/SessionMetaContext";
import {
  SessionMessagesContext,
  type SessionMessagesContextValue,
  useSessionMessagesContext,
} from "@/context/SessionMessagesContext";

const cacheKey = (workspaceSlug: string, sessionId: string): string =>
  `${workspaceSlug}:${sessionId}`;

/**
 * Legacy merged shape. New consumers should depend on
 * `useSessionMetaContext` or `useSessionMessagesContext` directly so they
 * don't re-render on the half of the world they don't read. This shim is
 * here for components that still straddle both halves.
 */
export type SessionContextValue = SessionMetaContextValue & SessionMessagesContextValue;

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const session = useSession();
  const { setMessageCache, refreshSessionMeta } = session;

  const sessionCreatedListenersRef = useRef<Set<() => void>>(new Set());

  const appendStartingMessages = useCallback(
    (ws: string, sid: string, items: Message[]) => {
      const key = cacheKey(ws, sid);
      setMessageCache((prev) => ({
        ...prev,
        [key]: [...(prev[key] ?? []), ...items],
      }));
    },
    [setMessageCache],
  );

  const finalizeAssistantMessage = useCallback(
    (
      ws: string,
      sid: string,
      content: string,
      referencedFiles?: ReferencedFile[],
      toolCalls?: ToolCall[],
      reasoningContent?: string | null,
      reasoningDurationS?: number | null,
    ) => {
      const key = cacheKey(ws, sid);
      setMessageCache((prev) => {
        const msgs = prev[key];
        if (!msgs || msgs.length === 0) return prev;
        const next = [...msgs];
        const last = next[next.length - 1];
        next[next.length - 1] = {
          ...last,
          content,
          referencedFiles: referencedFiles ?? last.referencedFiles,
          toolCalls: toolCalls ?? last.toolCalls,
          reasoningContent: reasoningContent ?? last.reasoningContent,
          reasoningDurationS: reasoningDurationS ?? last.reasoningDurationS,
        };
        return { ...prev, [key]: next };
      });
    },
    [setMessageCache],
  );

  const replaceMessages = useCallback(
    (ws: string, sid: string, messages: Message[]) => {
      const key = cacheKey(ws, sid);
      setMessageCache((prev) => ({ ...prev, [key]: messages }));
    },
    [setMessageCache],
  );

  const migrateBucket = useCallback(
    (ws: string, fromSid: string, toSid: string): boolean => {
      const fromKey = cacheKey(ws, fromSid);
      const toKey = cacheKey(ws, toSid);
      let migrated = false;
      setMessageCache((prev) => {
        const src = prev[fromKey];
        if (!src) return prev;
        migrated = true;
        const { [fromKey]: _drop, ...rest } = prev;
        return { ...rest, [toKey]: src };
      });
      return migrated;
    },
    [setMessageCache],
  );

  // Swap optimistic temp-u / temp-a ids on the last two messages of this
  // session's cache bucket for their real DB UUIDs. The SSE stream now
  // delivers these ids inline, so the post-stream message refetch is gone —
  // along with the race window between "stream ends" and "DB fetch resolves"
  // that the rapid-sends test was catching.
  const swapMessageIds = useCallback(
    (ws: string, sid: string, userId: string | null, assistantId: string | null) => {
      if (!userId && !assistantId) return;
      const key = cacheKey(ws, sid);
      setMessageCache((prev) => {
        const msgs = prev[key];
        if (!msgs || msgs.length === 0) return prev;
        const next = [...msgs];
        // Walk backwards: last message is the assistant turn just streamed;
        // the message before it is the user turn that triggered it.
        for (let i = next.length - 1; i >= 0 && i >= next.length - 2; i--) {
          const m = next[i];
          if (!m.id || !m.id.startsWith("temp-")) continue;
          if (m.role === "assistant" && assistantId) {
            next[i] = { ...m, id: assistantId };
          } else if (m.role === "user" && userId) {
            next[i] = { ...m, id: userId };
          }
        }
        return { ...prev, [key]: next };
      });
    },
    [setMessageCache],
  );

  const notifySessionCreated = useCallback(
    (_optimisticId: string, _realId: string) => {
      // Title refresh only — message-history refetch is no longer needed
      // because the SSE stream delivers real message ids inline.
      refreshSessionMeta();
      sessionCreatedListenersRef.current.forEach((fn) => fn());
    },
    [refreshSessionMeta],
  );

  const subscribeSessionCreated = useCallback((fn: () => void) => {
    sessionCreatedListenersRef.current.add(fn);
    return () => {
      sessionCreatedListenersRef.current.delete(fn);
    };
  }, []);

  const metaValue = useMemo<SessionMetaContextValue>(
    () => ({
      currentSession: session.currentSession,
      workspace: session.workspace,
      sessionTitle: session.sessionTitle,
      isInitialLoading: session.isInitialLoading,
      navigateToSession: session.navigateToSession,
      prefetchSession: session.prefetchSession,
      streamingSessionIdsRef: session.streamingSessionIdsRef,
      notifySessionCreated,
      subscribeSessionCreated,
    }),
    [
      session.currentSession,
      session.workspace,
      session.sessionTitle,
      session.isInitialLoading,
      session.navigateToSession,
      session.prefetchSession,
      session.streamingSessionIdsRef,
      notifySessionCreated,
      subscribeSessionCreated,
    ],
  );

  const messagesValue = useMemo<SessionMessagesContextValue>(
    () => ({
      messages: session.messages,
      appendStartingMessages,
      finalizeAssistantMessage,
      replaceMessages,
      migrateBucket,
      swapMessageIds,
    }),
    [
      session.messages,
      appendStartingMessages,
      finalizeAssistantMessage,
      replaceMessages,
      migrateBucket,
      swapMessageIds,
    ],
  );

  return (
    <SessionMetaContext.Provider value={metaValue}>
      <SessionMessagesContext.Provider value={messagesValue}>
        {children}
      </SessionMessagesContext.Provider>
    </SessionMetaContext.Provider>
  );
}

/**
 * Legacy merged hook. Returns the union of meta + messages so straddling
 * consumers (ActiveSession, useInference) keep their existing call sites
 * during the F4 migration window. Components that read only meta OR only
 * messages should prefer the narrow hooks.
 */
export function useSessionContext(): SessionContextValue {
  const meta = useSessionMetaContext();
  const messages = useSessionMessagesContext();
  return useMemo(() => ({ ...meta, ...messages }), [meta, messages]);
}

// Re-export the narrow hooks here so callers can import from one path.
export { useSessionMetaContext, useSessionMessagesContext };
