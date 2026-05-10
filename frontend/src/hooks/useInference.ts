import { useState, useRef, useCallback } from "react";
import { Message } from "@/types/chat";
import { APP_CONFIG } from "@/utils/constants";

export function useInference(
  workspace: string,
  setMessageCache: React.Dispatch<React.SetStateAction<Record<string, Message[]>>>,
  streamingSessionIdsRef: React.MutableRefObject<Set<string>>,
  onSessionCreated: (id: string) => void
) {
  const [isProcessing, setIsProcessing] = useState(false);
  const abortControllersRef = useRef<Map<string, AbortController>>(new Map());

  const sendMessage = useCallback(async (text: string, activeSessionId: string | null, model: string): Promise<string> => {
    setIsProcessing(true);
    const controller = new AbortController();
    
    const streamTargetId = activeSessionId || "temp_new_chat";
    abortControllersRef.current.set(streamTargetId, controller);
    streamingSessionIdsRef.current.add(streamTargetId);

    setMessageCache(prev => ({
      ...prev,
      [streamTargetId]: [
        ...(prev[streamTargetId] || []),
        { role: "user", content: text, timestamp: new Date().toISOString() },
        { role: "assistant", content: "", timestamp: new Date().toISOString() }
      ]
    }));

    let finalSessionId: string | null = activeSessionId;

    try {
      const res = await fetch(`${APP_CONFIG.API_URL}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          prompt: text, 
          session_id: activeSessionId, // This is null for first prompt
          mode: workspace, 
          model 
        }),
        signal: controller.signal
      });

      if (!res.ok) throw new Error(`HTTP Error ${res.status}`);

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let fullAssistantMessage = "";
      let lineBuffer = ""; // THE FIX: Stores partial JSON lines

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          
          lineBuffer += decoder.decode(value, { stream: true });
          const lines = lineBuffer.split("\n");
          
          // Keep the last (potentially incomplete) line in the buffer
          lineBuffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.trim()) continue;
            try {
              const parsed = JSON.parse(line);
              
              if (parsed.status === "started" && parsed.session_id && !finalSessionId) {
                const newId = parsed.session_id;
                finalSessionId = newId;
                streamingSessionIdsRef.current.add(newId);
                
                setMessageCache(prev => {
                  const newCache = { ...prev };
                  newCache[newId] = [...(newCache[streamTargetId] || [])];
                  delete newCache[streamTargetId];
                  return newCache;
                });
                onSessionCreated(newId);
              }

              if (parsed.chunk) {
                fullAssistantMessage += parsed.chunk;
                const currentKey = finalSessionId || streamTargetId;
                
                setMessageCache(prev => {
                  const msgs = prev[currentKey] || [];
                  if (msgs.length === 0) return prev;
                  const newMsgs = [...msgs];
                  newMsgs[newMsgs.length - 1] = { ...newMsgs[newMsgs.length - 1], content: fullAssistantMessage };
                  return { ...prev, [currentKey]: newMsgs };
                });
              }
            } catch (err) {
                lineBuffer = line + lineBuffer;
            }
          }
        }
      }
      return finalSessionId || streamTargetId;
    } catch (error: any) {
      if (error.name !== 'AbortError') console.error("Stream failed", error);
      return streamTargetId;
    } finally {
      setIsProcessing(false);
      
      // Clean up the optimistic ID
      streamingSessionIdsRef.current.delete(streamTargetId);
      
      // THE FIX: Also clean up the real backend ID so the spinner stops!
      if (finalSessionId) {
        streamingSessionIdsRef.current.delete(finalSessionId);
      }
      
      window.dispatchEvent(new Event("chatCreated"));
    }
  }, [workspace, setMessageCache, streamingSessionIdsRef, onSessionCreated]);

  return { 
    isProcessing, 
    sendMessage, 
    stopInference: (sessionId?: string | null) => {
      const id = sessionId || "temp_new_chat";
      abortControllersRef.current.get(id)?.abort();
    } 
  };
}