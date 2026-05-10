"use client";

import React, { createContext, useContext, useState } from "react";
import { useSession } from "@/hooks/useSession";
import { useUploader } from "@/hooks/useUploader";
import { useInference } from "@/hooks/useInference";
import { useTestSuite } from "@/hooks/useTestSuite";
import { APP_CONFIG } from "@/utils/constants";

const ChatContext = createContext<any>(null);

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const [selectedModel, setSelectedModel] = useState(() => 
    typeof window !== 'undefined' ? localStorage.getItem("pryzm_model") || APP_CONFIG.DEFAULT_MODEL : APP_CONFIG.DEFAULT_MODEL
  );
  
  const [pendingSessionId, setPendingSessionId] = useState<string | null>(null);
  const session = useSession();
  
  const uploader = useUploader(session.workspace, (newId) => {
    // When a file is uploaded to a brand new chat, generate the identity immediately
    if (!session.currentSession) {
        setPendingSessionId(newId);
        session.navigateToSession(newId);
    }
  });

  const ai = useInference(
    session.workspace, 
    session.setMessageCache, 
    session.streamingSessionIdsRef, 
    (oldId, newId) => {
      // HANDOVER: Link TestSuite state from whatever ID it was using to the new one
      tester.linkSession(oldId, newId);
      
      // If we are currently looking at the old ID (or null), update the URL
      const currentUrlId = new URLSearchParams(window.location.search).get("session");
      if (!currentUrlId || currentUrlId === oldId) {
        session.navigateToSession(newId);
      }
      setPendingSessionId(null);
    }
  );

  const tester = useTestSuite((text, sId) => ai.sendMessage(text, sId, selectedModel));

  const currentKey = session.currentSession || "temp_new_chat";
  const currentIsProcessing = session.streamingSessionIdsRef.current.has(currentKey);
  const currentIsTesting = tester.activeTestSessions.has(currentKey);

  const handleInference = async (rawPrompt: string) => {
    if (!rawPrompt.trim() || currentIsProcessing) return;

    const successfulUploads = uploader.uploads.filter((u: any) => u.status === 'success');
    let attachedPrefix = successfulUploads.map((u: any) => `[Attached_File:${u.file.name}]`).join('\n');
    if (attachedPrefix) attachedPrefix += '\n';
    
    const textToSend = attachedPrefix + rawPrompt;
    uploader.clearQueue();
    
    // Always prefer the URL session, then the pending upload session, then null
    const activeIdToUse = session.currentSession || pendingSessionId;
    
    await ai.sendMessage(textToSend, activeIdToUse, selectedModel);
  };

  const stopAllInference = () => {
    tester.stopTestSuite(session.currentSession); 
    ai.stopInference(session.currentSession); 
  };

  const value = {
    session, uploader, ai, tester,
    selectedModel, setSelectedModel,
    currentIsProcessing, currentIsTesting,
    handleInference, stopAllInference
  };

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export const useChatContext = () => useContext(ChatContext);