"use client";

import React, { createContext, useContext, useState } from "react";
import { useSession } from "@/hooks/useSession";
import { useUploader } from "@/hooks/useUploader";
import { useInference } from "@/hooks/useInference";
import { useTestSuite } from "@/hooks/useTestSuite";
import { useMessageActions } from "@/hooks/useMessageActions";
import { APP_CONFIG } from "@/utils/constants";
import { useWorkspaces, Workspace } from "@/hooks/useWorkspaces";

/**
 * Compose all chat-related hooks into a single value object. The context's
 * type is inferred from this hook's return shape (see ChatContextValue
 * below), so adding/removing fields here automatically propagates to every
 * consumer of useChatContext() with no separate interface to maintain.
 */
function useChatValue() {
  const [selectedModel, setSelectedModel] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("pryzm_model") || APP_CONFIG.DEFAULT_MODEL;
    }
    return APP_CONFIG.DEFAULT_MODEL;
  });

  const session = useSession();
  const workspacesApi = useWorkspaces();
  const activeWorkspace: Workspace | null =
    workspacesApi.workspaces.find((w) => w.slug === session.workspace) ?? null;

  const uploader = useUploader(session.workspace);

  const ai = useInference(
    session.workspace,
    session.setMessageCache,
    session.streamingSessionIdsRef,
    (oldId, newId) => {
      tester.linkSession(oldId, newId);

      const params = new URLSearchParams(window.location.search);
      const currentUrlId = params.get("session");

      if (!currentUrlId || currentUrlId === oldId) {
        session.navigateToSession(newId);
      }
    }
  );

  const tester = useTestSuite((text, sId) =>
    ai.sendMessage(text, sId, selectedModel)
  );

  const currentKey = session.currentSession || "temp_new_chat";

  const currentIsProcessing =
    session.streamingSessionIdsRef.current.has(currentKey);

  const currentIsTesting = tester.activeTestSessions.has(currentKey);

  const handleInference = async (rawPrompt: string) => {
    if (!rawPrompt.trim() || currentIsProcessing) return;

    let activeIdToUse = session.currentSession;
    if (activeIdToUse === "temp_new_chat") {
      activeIdToUse = null;
    }

    const pendingUploads = uploader.uploads.filter(
      (u) => u.status === "pending"
    );

    if (pendingUploads.length > 0) {
      await uploader.processUploadQueue(pendingUploads);
    }

    const successfulUploads = uploader.uploads.filter(
      (u) => u.status === "success"
    );

    const documentIds = successfulUploads
      .map((u) => u.document_id)
      .filter((id): id is string => Boolean(id));

    let attachedPrefix = successfulUploads
      .map((u) => `[Attached_File:${u.file.name}]`)
      .join("\n");

    if (attachedPrefix) {
      attachedPrefix += "\n";
    }

    const textToSend = attachedPrefix + rawPrompt;
    uploader.clearQueue();

    await ai.sendMessage(
      textToSend,
      activeIdToUse,
      selectedModel,
      documentIds
    );
  };

  const stopAllInference = () => {
    tester.stopTestSuite(session.currentSession);
    ai.stopInference(session.currentSession);
  };

  const msgActions = useMessageActions(
    session.workspace,
    currentKey,
    session.messages,
    session.setMessageCache,
    ai.sendMessage,
    session.navigateToSession,
    selectedModel
  );

  return {
    session,
    uploader,
    ai,
    tester,
    selectedModel,
    setSelectedModel,
    currentIsProcessing,
    currentIsTesting,
    handleInference,
    stopAllInference,
    msgActions,
    workspacesApi,
    activeWorkspace,
  };
}

export type ChatContextValue = ReturnType<typeof useChatValue>;

const ChatContext = createContext<ChatContextValue | null>(null);

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const value = useChatValue();
  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

/**
 * Throws if called outside <ChatProvider>. Callers can therefore treat the
 * returned object as always-defined and let TypeScript narrow accordingly.
 */
export const useChatContext = (): ChatContextValue => {
  const ctx = useContext(ChatContext);
  if (!ctx) {
    throw new Error("useChatContext must be used inside <ChatProvider>");
  }
  return ctx;
};
