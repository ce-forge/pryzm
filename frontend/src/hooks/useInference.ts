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
  
  // Map to handle independent concurrent streams
  const abortControllersRef = useRef<Map<string, AbortController>>(new Map());

  const sendMessage = useCallback(async (text: string, activeSessionId: string | null, model: string) => {
    setIsProcessing(true);
    const controller = new AbortController();
    
    let streamTargetId: string | null = activeSessionId;
    const lookupId = streamTargetId || "temp_new_chat";

    abortControllersRef.current.set(lookupId, controller);
    if (streamTargetId) streamingSessionIdsRef.current.add(streamTargetId);

    setMessageCache(prev => ({
      ...prev,
      [lookupId]: [
        ...(prev[lookupId] || []),
        { role: "user", content: text, timestamp: new Date().toISOString() },
        { role: "assistant", content: "", timestamp: new Date().toISOString() }
      ]
    }));

    try {
      const res = await fetch(`${APP_CONFIG.API_URL}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: text, session_id: activeSessionId, mode: workspace, model }),
        signal: controller.signal // Use mapped controller
      });

      if (!res.ok) throw new Error(`HTTP Error ${res.status}`);

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let fullAssistantMessage = "";
      let lastUpdateTime = 0;

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          
          const lines = decoder.decode(value).split("\n");
          let chunkUpdated = false; // Track changes per payload

          for (const line of lines) {
            if (!line.trim()) continue;
            try {
              const parsed = JSON.parse(line);
              
              if (parsed.status === "started" && parsed.session_id && !streamTargetId) {
                streamTargetId = parsed.session_id;
                const newId = parsed.session_id;
                streamingSessionIdsRef.current.add(newId);
                
                // Migrate the abort controller to the new persistent ID
                abortControllersRef.current.set(newId, controller);
                abortControllersRef.current.delete("temp_new_chat");
                
                setMessageCache(prev => {
                  const newCache = { ...prev };
                  newCache[newId] = newCache["temp_new_chat"] || [];
                  delete newCache["temp_new_chat"];
                  return newCache;
                });

                onSessionCreated(newId);
              }

              if (parsed.chunk) {
                fullAssistantMessage += parsed.chunk;
                chunkUpdated = true;
              }
            } catch (err) {}
          }
          
          // Exactly ONE state update per fetch payload
          if (chunkUpdated) {
            const now = Date.now();
            const currentIdKey = streamTargetId || "temp_new_chat";
            
            if (now - lastUpdateTime > 40) {
              setMessageCache(prev => {
                const msgs = prev[currentIdKey] || [];
                if (msgs.length === 0) return prev;
                const newMsgs = [...msgs];
                newMsgs[newMsgs.length - 1] = { ...newMsgs[newMsgs.length - 1], content: fullAssistantMessage };
                return { ...prev, [currentIdKey]: newMsgs };
              });
              lastUpdateTime = now;
            }
          }
        }
        
        // Final flush when the stream finishes completely
        const finalIdKey = streamTargetId || "temp_new_chat";
        setMessageCache(prev => {
          const msgs = prev[finalIdKey] || [];
          if (msgs.length === 0) return prev;
          const newMsgs = [...msgs];
          newMsgs[newMsgs.length - 1] = { ...newMsgs[newMsgs.length - 1], content: fullAssistantMessage };
          return { ...prev, [finalIdKey]: newMsgs };
        });
      }
    } catch (error: any) {
      // Catch the AbortError specifically and swallow it silently
      if (error.name === 'AbortError') {
        console.log("Test suite / Inference stopped by user.");
      } else {
        console.error("Stream failed", error);
      }
    } finally {
      setIsProcessing(false);
      if (streamTargetId) streamingSessionIdsRef.current.delete(streamTargetId);
      window.dispatchEvent(new Event("chatCreated"));
    }
    
    return streamTargetId;
  }, [workspace, setMessageCache, streamingSessionIdsRef, onSessionCreated]);

  return { 
    isProcessing, 
    sendMessage, 
    stopInference: (sessionId?: string | null) => {
      const id = sessionId || "temp_new_chat";
      try {
        const controller = abortControllersRef.current.get(id);
        if (controller) {
          controller.abort();
          abortControllersRef.current.delete(id);
        }
      } catch (e) {}
    } 
  };
}