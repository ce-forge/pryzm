"use client";

import React, { createContext, useContext, useState } from "react";
import { useSession } from "@/hooks/useSession";
import { useUploader } from "@/hooks/useUploader";
import { useInference } from "@/hooks/useInference";
import { useTestSuite } from "@/hooks/useTestSuite";
import { APP_CONFIG } from "@/utils/constants";

const ChatContext = createContext<any>(null);

export function ChatProvider({ children }: { children: React.ReactNode }) {
  
  const [selectedModel, setSelectedModel] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("pryzm_model") || APP_CONFIG.DEFAULT_MODEL;
    }
    return APP_CONFIG.DEFAULT_MODEL;
  });

  const session = useSession();
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
      (u: any) => u.status === "pending"
    );

    if (pendingUploads.length > 0) {
      await uploader.processUploadQueue(pendingUploads);
    }

    const successfulUploads = uploader.uploads.filter(
      (u: any) => u.status === "success"
    );

    const documentIds = successfulUploads
      .map((u: any) => u.document_id)
      .filter(Boolean);

    let attachedPrefix = successfulUploads
      .map((u: any) => `[Attached_File:${u.file.name}]`)
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

  const value = {
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
  };

  return (
    <ChatContext.Provider value={value}>
      {children}
    </ChatContext.Provider>
  );
}

export const useChatContext = () => useContext(ChatContext);