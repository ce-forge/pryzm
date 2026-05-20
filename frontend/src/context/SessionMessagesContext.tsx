"use client";

import { createContext, useContext } from "react";
import { Message, ReferencedFile, ToolCall } from "@/types/chat";

export interface SessionMessagesContextValue {
  messages: Message[];
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
    reasoningContent?: string | null,
    reasoningDurationS?: number | null,
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
}

export const SessionMessagesContext = createContext<SessionMessagesContextValue | null>(null);

export function useSessionMessagesContext(): SessionMessagesContextValue {
  const ctx = useContext(SessionMessagesContext);
  if (!ctx) throw new Error("useSessionMessagesContext must be used inside <SessionProvider>");
  return ctx;
}
