"use client";

import React, { createContext, useCallback, useContext, useMemo, useRef } from "react";
import { useSession } from "@/hooks/useSession";
import { Message } from "@/types/chat";

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
  notifySessionCreated: (
    optimisticSessionId: string,
    realSessionId: string,
  ) => void;
  subscribeSessionCreated: (fn: () => void) => () => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const session = useSession();
  const { setMessageCache, loadSessionData } = session;

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
    (ws: string, sid: string, content: string) => {
      const key = cacheKey(ws, sid);
      setMessageCache((prev) => {
        const msgs = prev[key];
        if (!msgs || msgs.length === 0) return prev;
        const next = [...msgs];
        next[next.length - 1] = { ...next[next.length - 1], content };
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

  const notifySessionCreated = useCallback(
    (_optimisticId: string, _realId: string) => {
      loadSessionData(true);
      sessionCreatedListenersRef.current.forEach((fn) => fn());
    },
    [loadSessionData],
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
