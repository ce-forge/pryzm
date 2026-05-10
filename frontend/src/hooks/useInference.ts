import { useState, useRef, useCallback, useEffect } from "react";
import { Message } from "@/types/chat";
import { APP_CONFIG } from "@/utils/constants";

export function useInference(
  workspace: string,
  setMessageCache: React.Dispatch<React.SetStateAction<Record<string, Message[]>>>,
  streamingSessionIdsRef: React.MutableRefObject<Set<string>>,
  onSessionCreated: (oldId: string, newId: string) => void
) {
  const [isProcessing, setIsProcessing] = useState(false);
  const [streamingContent, setStreamingContent] = useState<Record<string, string>>({});
  const abortControllersRef = useRef<Map<string, AbortController>>(new Map());

  // Prevent accidental refreshes while generating
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (isProcessing) {
        e.preventDefault();
        e.returnValue = "AI is still generating. If you refresh, the response will be interrupted.";
        return e.returnValue;
      }
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [isProcessing]);

  const sendMessage = useCallback(async (text: string, activeSessionId: string | null, model: string, attachments: string[] = []): Promise<string> => {
    setIsProcessing(true);
    
    const isNewChat = !activeSessionId;
    const streamTargetId = activeSessionId || `optimistic-${Date.now()}`;
    
    setStreamingContent(prev => ({ ...prev, [streamTargetId]: "" }));

    setMessageCache(prev => {
      const existing = prev[streamTargetId] || [];
      return {
        ...prev,
        [streamTargetId]: [
          ...existing,
          { role: "user", content: text, timestamp: new Date().toISOString() },
          { role: "assistant", content: "", timestamp: new Date().toISOString() }
        ]
      };
    });

    if (isNewChat) {
      onSessionCreated("temp_new_chat", streamTargetId); 
    }

    const controller = new AbortController();
    abortControllersRef.current.set(streamTargetId, controller);
    streamingSessionIdsRef.current.add(streamTargetId);

    let finalSessionId: string | null = null;

    try {
      const res = await fetch(`${APP_CONFIG.API_URL}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
            prompt: text, 
            session_id: isNewChat ? null : activeSessionId, 
            mode: workspace, 
            model,
            attachments
        }),
        signal: controller.signal
      });

      if (!res.ok) throw new Error(`HTTP Error ${res.status}`);

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let fullAssistantMessage = "";
      let lineBuffer = ""; 
      let lastUpdateTime = 0;

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          
          lineBuffer += decoder.decode(value, { stream: true });
          const lines = lineBuffer.split("\n");
          lineBuffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.trim()) continue;
            try {
              const parsed = JSON.parse(line);
              
              if (parsed.status === "started" && parsed.session_id && isNewChat && !finalSessionId) {
                const realUuid = parsed.session_id;
                finalSessionId = realUuid;
                
                streamingSessionIdsRef.current.add(realUuid);

                setStreamingContent(prev => {
                    const next = { ...prev };
                    next[realUuid] = next[streamTargetId] || "";
                    delete next[streamTargetId];
                    return next;
                });
                
                const activeController = abortControllersRef.current.get(streamTargetId);
                if (activeController) abortControllersRef.current.set(realUuid, activeController);

                setMessageCache(prev => {
                  const newCache = { ...prev };
                  newCache[realUuid] = [...(newCache[streamTargetId] || [])];
                  delete newCache[streamTargetId];
                  return newCache;
                });

                onSessionCreated(streamTargetId, realUuid);
              }

              if (parsed.chunk) {
                fullAssistantMessage += parsed.chunk;
                const now = Date.now();
                if (now - lastUpdateTime > 30) {
                  setStreamingContent(prev => ({
                    ...prev,
                    [finalSessionId || streamTargetId]: fullAssistantMessage
                  }));
                  lastUpdateTime = now;
                }
              }
            } catch (err) { 
               // Ignore partial JSON parsing errors mid-stream
            }
          }
        }
        
        const finalKey = finalSessionId || streamTargetId;
        setMessageCache(prev => {
          const msgs = prev[finalKey] || [];
          if (msgs.length === 0) return prev;
          const newMsgs = [...msgs];
          newMsgs[newMsgs.length - 1] = { ...newMsgs[newMsgs.length - 1], content: fullAssistantMessage };
          return { ...prev, [finalKey]: newMsgs };
        });
      }
      return (finalSessionId || streamTargetId) as string;
      
    } catch (error: any) {
      
      // --- THE UX FIX: VISUAL ERROR HANDLING ---
      if (error.name !== 'AbortError') {
        console.error("Inference stream failed:", error);
        
        const finalKey = finalSessionId || streamTargetId;
        
        setMessageCache(prev => {
          const msgs = prev[finalKey] || [];
          if (msgs.length === 0) return prev;
          
          const newMsgs = [...msgs];
          const lastMsg = newMsgs[newMsgs.length - 1];
          
          // Determine if it failed immediately or mid-generation
          const isMidStream = !!lastMsg.content || !!streamingContent[finalKey];
          
          const errorMessage = isMidStream 
            ? `${streamingContent[finalKey] || lastMsg.content}\n\n> ⚠️ **Connection Interrupted:** The AI stopped responding. Please try again.` 
            : `> ⚠️ **Generation Failed:** Could not connect to the inference engine. Ensure the backend and Ollama are running.`;
            
          newMsgs[newMsgs.length - 1] = { ...lastMsg, content: errorMessage };
          return { ...prev, [finalKey]: newMsgs };
        });
      }
      return (finalSessionId || streamTargetId) as string;
      
    } finally {
      setIsProcessing(false);
      setStreamingContent(prev => {
        const newMap = { ...prev };
        delete newMap[streamTargetId];
        if (finalSessionId) delete newMap[finalSessionId];
        return newMap;
      });
      
      streamingSessionIdsRef.current.delete(streamTargetId);
      abortControllersRef.current.delete(streamTargetId); 
      if (finalSessionId) {
        streamingSessionIdsRef.current.delete(finalSessionId);
        abortControllersRef.current.delete(finalSessionId);
      }
      window.dispatchEvent(new Event("chatCreated"));
    }
  }, [workspace, setMessageCache, streamingSessionIdsRef, onSessionCreated]);

  return { 
    isProcessing, 
    streamingContent, 
    sendMessage, 
    stopInference: (sessionId?: string | null) => {
      const id = sessionId || "temp_new_chat";
      abortControllersRef.current.get(id)?.abort();
    } 
  };
}