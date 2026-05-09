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

export default function Home() {
  const [isMounted, setIsMounted] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  
  const [selectedModel, setSelectedModel] = useState(() => 
    typeof window !== 'undefined' ? localStorage.getItem("pryzm_model") || APP_CONFIG.DEFAULT_MODEL : APP_CONFIG.DEFAULT_MODEL
  );

  const session = useSession();
  const promptState = usePrompt(session.messages);
  
  const uploader = useUploader(session.workspace, (newId) => {
    session.navigateToSession(newId);
  });

  const ai = useInference(
    session.workspace, 
    session.setMessageCache, 
    session.streamingSessionIdsRef, 
    (newId) => session.navigateToSession(newId)
  );

  const tester = useTestSuite((text, sId) => ai.sendMessage(text, sId, selectedModel));

  useEffect(() => {
    if (session.currentSession && tester.activeTestSessions.has("temp_new_chat")) {
      tester.linkSession("temp_new_chat", session.currentSession);
    }
  }, [session.currentSession, tester.activeTestSessions, tester.linkSession]);

  const handleInference = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!promptState.prompt.trim() || ai.isProcessing) return;

    promptState.saveToHistory(promptState.prompt); 

    const successfulUploads = uploader.uploads.filter(u => u.status === 'success');
    let attachedPrefix = successfulUploads.map(u => `[Attached_File:${u.file.name}]`).join('\n');
    if (attachedPrefix) attachedPrefix += '\n';
    
    const textToSend = attachedPrefix + promptState.prompt;
    
    promptState.setPrompt("");
    uploader.clearQueue();
    
    await ai.sendMessage(textToSend, session.currentSession, selectedModel);
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
        isSidebarOpen={isSidebarOpen} 
        setIsSidebarOpen={setIsSidebarOpen} 
        handleInference={handleInference}
        handleKeyDown={(e: any) => promptState.handleKeyDown(e, () => handleInference())}
        isProcessing={session.streamingSessionIdsRef.current.has(session.currentSession || "temp_new_chat")}
        
        isAutoTesting={tester.activeTestSessions.has(session.currentSession || "temp_new_chat")}
        
        runTestSuite={(type: any) => tester.runTestSuite(type, session.currentSession)}
        
        stopAutoTest={() => { tester.stopTestSuite(session.currentSession); ai.stopInference(session.currentSession); }}
        
        processUploadQueue={(files) => uploader.processUploadQueue(files, session.currentSession)}
      />
    </div>
  );
}