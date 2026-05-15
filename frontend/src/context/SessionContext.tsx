"use client";

import React, { createContext, useCallback, useContext, useMemo, useRef } from "react";
import { useSession } from "@/hooks/useSession";
import { Message, ReferencedFile, ToolCall } from "@/types/chat";

const cacheKey = (workspaceSlug: string, sessionId: string): string =>
  `${workspaceSlug}:${sessionId}`;

interface SessionContextValue {
  currentSession: string | null;
  workspace: string;
  sessionTitle: string;
  isInitialLoading: boolean;
  activeCacheKey: string;
  navigateToSession: (id: string) => void;
  prefetchSession: (id: string) => Promise<void>;
  streamingSessionIdsRef: React.MutableRefObject<Set<string>>;

  messages: Message[];
  getMessages: (workspaceSlug: string, sessionId: string) => Message[];
  appendStartingMessages: (
    workspaceSlug: string,
    sessionId: string,
    items: Message[],
  ) => void;
  finalizeAssistantMessage: (
    workspaceSlug: string,
    sessionId: string,
    content: string,
    referencedFiles?: ReferencedFile[],
    toolCalls?: ToolCall[],
  ) => void;
  replaceMessages: (
    workspaceSlug: string,
    sessionId: string,
    messages: Message[],
  ) => void;
  migrateBucket: (
    workspaceSlug: string,
    fromSessionId: string,
    toSessionId: string,
  ) => boolean;
  /**
   * Swap temp- IDs on the last user and/or assistant messages of a session
   * for their real DB UUIDs. Called inline from the SSE handler so the cache
   * has real IDs without any post-stream /sessions/{id} refetch.
   */
  swapMessageIds: (
    workspaceSlug: string,
    sessionId: string,
    userMessageId: string | null,
    assistantMessageId: string | null,
  ) => void;
  notifySessionCreated: (
    optimisticSessionId: string,
    realSessionId: string,
  ) => void;
  subscribeSessionCreated: (fn: () => void) => () => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const session = useSession();
  const { setMessageCache, refreshSessionMeta } = session;

  const sessionCreatedListenersRef = useRef<Set<() => void>>(new Set());

  const getMessages = useCallback(
    (ws: string, sid: string): Message[] =>
      session.messageCache[cacheKey(ws, sid)] ?? [],
    [session.messageCache],
  );

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
    (ws: string, sid: string, content: string, referencedFiles?: ReferencedFile[], toolCalls?: ToolCall[]) => {
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

  const value = useMemo<SessionContextValue>(
    () => ({
      currentSession: session.currentSession,
      workspace: session.workspace,
      sessionTitle: session.sessionTitle,
      isInitialLoading: session.isInitialLoading,
      activeCacheKey: session.activeCacheKey,
      navigateToSession: session.navigateToSession,
      prefetchSession: session.prefetchSession,
      streamingSessionIdsRef: session.streamingSessionIdsRef,
      messages: session.messages,
      getMessages,
      appendStartingMessages,
      finalizeAssistantMessage,
      replaceMessages,
      migrateBucket,
      swapMessageIds,
      notifySessionCreated,
      subscribeSessionCreated,
    }),
    [
      session.currentSession,
      session.workspace,
      session.sessionTitle,
      session.isInitialLoading,
      session.activeCacheKey,
      session.navigateToSession,
      session.prefetchSession,
      session.streamingSessionIdsRef,
      session.messages,
      getMessages,
      appendStartingMessages,
      finalizeAssistantMessage,
      replaceMessages,
      migrateBucket,
      swapMessageIds,
      notifySessionCreated,
      subscribeSessionCreated,
    ],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSessionContext(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSessionContext must be used inside <SessionProvider>");
  return ctx;
}
