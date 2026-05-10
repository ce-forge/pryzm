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

  const sendMessage = useCallback(async (
    text: string, 
    activeSessionId: string | null, 
    model: string, 
    attachments: string[] = [],
    skipUserAdd: boolean = false
  ): Promise<string> => {
    setIsProcessing(true);
    
    // FIX: Changed from const to let so we can swap it mid-flight
    let currentTargetId = activeSessionId || `optimistic-${Date.now()}`;
    
    setStreamingContent(prev => ({ ...prev, [currentTargetId]: "" }));

    let fullAssistantMessage = "";

    setMessageCache(prev => {
      const existing = prev[currentTargetId] || [];
      const newItems: Message[] = [];
      if (!skipUserAdd) {
        newItems.push({ id: `temp-${Date.now()}-u`, role: "user", content: text, timestamp: new Date().toISOString() });
      }
      newItems.push({ id: `temp-${Date.now()}-a`, role: "assistant", content: "", timestamp: new Date().toISOString() });
      return { ...prev, [currentTargetId]: [...existing, ...newItems] };
    });

    if (!activeSessionId) onSessionCreated("temp_new_chat", currentTargetId);

    const controller = new AbortController();
    abortControllersRef.current.set(currentTargetId, controller);
    streamingSessionIdsRef.current.add(currentTargetId);

    try {
      const res = await fetch(`${APP_CONFIG.API_URL}/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          prompt: text, 
          session_id: (activeSessionId === "temp_new_chat" || !activeSessionId) ? null : activeSessionId, 
          mode: workspace, model, attachments,
          skip_db_save: skipUserAdd 
        }),
        signal: controller.signal
      });

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let lineBuffer = "";

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
              
              // --- THE HANDOFF FIX ---
              if (parsed.status === "started" && parsed.session_id && !activeSessionId) {
                const newDbId = parsed.session_id;
                
                // 1. Tell the parent to update the URL
                onSessionCreated(currentTargetId, newDbId);

                // 2. Transfer the AbortController so the Stop button still works
                const activeController = abortControllersRef.current.get(currentTargetId);
                if (activeController) {
                    abortControllersRef.current.delete(currentTargetId);
                    abortControllersRef.current.set(newDbId, activeController);
                }

                // 3. Transfer the loading animation tracker
                streamingSessionIdsRef.current.delete(currentTargetId);
                streamingSessionIdsRef.current.add(newDbId);

                // 4. Transfer the UI Message History buckets
                setMessageCache(prev => {
                    const msgs = prev[currentTargetId] || [];
                    const { [currentTargetId]: removedItem, ...rest } = prev;
                    return { ...rest, [newDbId]: msgs };
                });

                // 5. Transfer the streaming text bucket
                setStreamingContent(prev => {
                    const content = prev[currentTargetId] || "";
                    const { [currentTargetId]: removedItem, ...rest } = prev;
                    return { ...rest, [newDbId]: content };
                });

                // 6. Adopt the new UUID for the remainder of the stream!
                currentTargetId = newDbId;
              }
              
              if (parsed.chunk) {
                fullAssistantMessage += parsed.chunk;
                setStreamingContent(prev => ({ ...prev, [currentTargetId]: fullAssistantMessage }));
              }
            } catch (e) {}
          }
        }
      }
    } catch (error: any) {
      console.log("Inference ended:", error.name);
    } finally {
      setIsProcessing(false);
      setMessageCache(prev => {
        const msgs = prev[currentTargetId] || [];
        if (msgs.length === 0) return prev;
        const newMsgs = [...msgs];
        newMsgs[newMsgs.length - 1] = { ...newMsgs[newMsgs.length - 1], content: fullAssistantMessage };
        return { ...prev, [currentTargetId]: newMsgs };
      });
      setStreamingContent(prev => { const { [currentTargetId]: removedItem, ...rest } = prev; return rest; });
      streamingSessionIdsRef.current.delete(currentTargetId);
      window.dispatchEvent(new Event("chatCreated"));
    }
    return currentTargetId;
  }, [workspace, setMessageCache, streamingSessionIdsRef, onSessionCreated]);

  return { 
    isProcessing, 
    streamingContent, 
    sendMessage, 
    stopInference: (id?: string | null) => {
      const target = id || "temp_new_chat";
      if (abortControllersRef.current.has(target)) {
        abortControllersRef.current.get(target)?.abort();
      } else {
        for (const [key, controller] of abortControllersRef.current.entries()) {
          if (key.startsWith("optimistic-")) controller.abort();
        }
      }
    } 
  };
}