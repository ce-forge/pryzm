"use client";

import React, { createContext, useContext } from "react";

export interface SessionMetaContextValue {
  currentSession: string | null;
  workspace: string;
  sessionTitle: string;
  isInitialLoading: boolean;
  navigateToSession: (id: string) => void;
  prefetchSession: (id: string) => Promise<void>;
  streamingSessionIdsRef: React.MutableRefObject<Set<string>>;
  notifySessionCreated: (
    optimisticSessionId: string,
    realSessionId: string,
  ) => void;
  subscribeSessionCreated: (fn: () => void) => () => void;
}

export const SessionMetaContext = createContext<SessionMetaContextValue | null>(null);

export function useSessionMetaContext(): SessionMetaContextValue {
  const ctx = useContext(SessionMetaContext);
  if (!ctx) throw new Error("useSessionMetaContext must be used inside <SessionProvider>");
  return ctx;
}
