"use client";

import { useEffect, useState } from "react";
import Sidebar from "@/components/Sidebar"; 
import ActiveSession from "@/components/ActiveSession";
import { useSession } from "@/hooks/useSession";
import { useUploader } from "@/hooks/useUploader";
import { useInference } from "@/hooks/useInference";
import { usePrompt } from "@/hooks/usePrompt";
import { useTestSuite } from "@/hooks/useTestSuite";
import { APP_CONFIG } from "@/utils/constants";
import { FileUpload } from "@/types/chat";

export default function Home() {
  const [isMounted, setIsMounted] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  
  // FIX: Track uploads that happen before a prompt is sent
  const [pendingSessionId, setPendingSessionId] = useState<string | null>(null);
  
  const [selectedModel, setSelectedModel] = useState(() => 
    typeof window !== 'undefined' ? localStorage.getItem("pryzm_model") || APP_CONFIG.DEFAULT_MODEL : APP_CONFIG.DEFAULT_MODEL
  );

  const session = useSession();
  const promptState = usePrompt(session.messages);
  
  const uploader = useUploader(session.workspace, (newId) => {
    // FIX (Issues 4 & 5): Do NOT navigate here. Just hold the ID silently.
    if (!session.currentSession) setPendingSessionId(newId);
  });

  const tester = useTestSuite((text, sId) => ai.sendMessage(text, sId, selectedModel));

  const ai = useInference(
    session.workspace, 
    session.setMessageCache, 
    session.streamingSessionIdsRef, 
    (newId) => {
      // FIX (Issue 1): Transfer the testing state to the new real ID
      tester.linkSession("temp_new_chat", newId);
      setPendingSessionId(null);
      session.navigateToSession(newId);
    }
  );

  const currentIsProcessing = session.currentSession 
    ? session.streamingSessionIdsRef.current.has(session.currentSession) 
    : session.streamingSessionIdsRef.current.has("temp_new_chat");

  const currentIsTesting = session.currentSession 
    ? tester.activeTestSessions.has(session.currentSession) 
    : tester.activeTestSessions.has("temp_new_chat");


  const handleInference = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    
    if (!promptState.prompt.trim() || currentIsProcessing) return;

    const successfulUploads = uploader.uploads.filter(u => u.status === 'success');
    let attachedPrefix = successfulUploads.map(u => `[Attached_File:${u.file.name}]`).join('\n');
    if (attachedPrefix) attachedPrefix += '\n';
    
    const textToSend = attachedPrefix + promptState.prompt;
    
    promptState.saveToHistory(promptState.prompt);
    promptState.setPrompt("");
    uploader.clearQueue();
    
    const activeIdToUse = session.currentSession || pendingSessionId;
    
    if (!session.currentSession && pendingSessionId) {
      session.navigateToSession(pendingSessionId);
      setPendingSessionId(null);
    }
    
    await ai.sendMessage(textToSend, activeIdToUse, selectedModel);
  };

  useEffect(() => {
    setIsMounted(true);
    if (window.innerWidth < 768) setIsSidebarOpen(false);
  }, []);

  if (!isMounted) return <div className="h-screen w-full bg-[#131314]" />;

  return (
    <div className="flex h-screen w-full bg-[#131314] text-[#e3e3e3] overflow-hidden font-sans">
      <Sidebar 
        isOpen={isSidebarOpen} 
        setIsOpen={setIsSidebarOpen} 
        selectedModel={selectedModel}
        setSelectedModel={setSelectedModel}
        streamingSessionIdsRef={session.streamingSessionIdsRef}
      />
      <ActiveSession 
        {...session}
        {...promptState}
        {...uploader}
        {...ai}
        {...tester}
        messages={session.isInitialLoading ? [] : session.messages}
        isLoadingHistory={session.isInitialLoading}
        isSidebarOpen={isSidebarOpen} 
        setIsSidebarOpen={setIsSidebarOpen} 
        handleInference={handleInference}
        handleKeyDown={(e: any) => promptState.handleKeyDown(e, handleInference)}
        isProcessing={currentIsProcessing}
        isAutoTesting={currentIsTesting}
        stopAutoTest={() => { 
            tester.stopTestSuite(session.currentSession); 
            ai.stopInference(session.currentSession); 
        }}
        processUploadQueue={(files: FileUpload[]) => uploader.processUploadQueue(files, session.currentSession)}
        runTestSuite={(type: any) => tester.runTestSuite(type, session.currentSession)}
      />
    </div>
  );
}