import { useState, useRef, useCallback, useEffect } from "react";
import { Message } from "@/types/chat";
import { apiFetch } from "@/utils/apiClient";

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
    
    const optimisticId = activeSessionId || `optimistic-${Date.now()}`;
    let realDbId: string | null = null; // Safely typed for TS
    
    setStreamingContent(prev => ({ ...prev, [optimisticId]: "" }));

    let fullAssistantMessage = "";

    setMessageCache(prev => {
      const existing = prev[optimisticId] || [];
      const newItems: Message[] = [];
      if (!skipUserAdd) {
        newItems.push({ id: `temp-${Date.now()}-u`, role: "user", content: text, timestamp: new Date().toISOString() });
      }
      newItems.push({ id: `temp-${Date.now()}-a`, role: "assistant", content: "", timestamp: new Date().toISOString() });
      return { ...prev, [optimisticId]: [...existing, ...newItems] };
    });

    if (!activeSessionId) onSessionCreated("temp_new_chat", optimisticId);

    const controller = new AbortController();
    abortControllersRef.current.set(optimisticId, controller);
    streamingSessionIdsRef.current.add(optimisticId);

    try {
      const res = await apiFetch("/analyze", {
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
        streamLoop: while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          lineBuffer += decoder.decode(value, { stream: true });
          const lines = lineBuffer.split("\n");
          lineBuffer = lines.pop() || "";
          for (const line of lines) {
            if (!line.trim()) continue;
            try {
              const parsed = JSON.parse(line);

              if (parsed.error) {
                // Error envelope from backend. Replace the streaming bubble with
                // the error message and stop processing further chunks.
                fullAssistantMessage = `⚠ ${parsed.error}`;
                setStreamingContent(prev => {
                  const next = { ...prev, [optimisticId]: fullAssistantMessage };
                  if (realDbId !== null) next[realDbId] = fullAssistantMessage;
                  return next;
                });
                break streamLoop;
              }

              // THE HANDOFF
              if (parsed.status === "started" && parsed.session_id && !activeSessionId) {
                const newDbId = parsed.session_id;
                realDbId = newDbId; // Store for the rest of the stream
                
                onSessionCreated(optimisticId, newDbId);

                const activeController = abortControllersRef.current.get(optimisticId);
                if (activeController) abortControllersRef.current.set(newDbId, activeController);

                streamingSessionIdsRef.current.add(newDbId);

                // Initialize the new bucket, but DO NOT delete optimistic yet!
                setMessageCache(prev => ({ ...prev, [newDbId]: prev[optimisticId] || [] }));
                setStreamingContent(prev => ({ ...prev, [newDbId]: prev[optimisticId] || "" }));
              }
              
              if (parsed.chunk) {
                fullAssistantMessage += parsed.chunk;
                
                // Stream into BOTH buckets so the UI never misses a chunk during URL change
                setStreamingContent(prev => {
                    const next = { ...prev, [optimisticId]: fullAssistantMessage };
                    if (realDbId !== null) {
                        next[realDbId] = fullAssistantMessage;
                    }
                    return next;
                });
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
        const msgs = prev[optimisticId] || [];
        if (msgs.length === 0) return prev;
        const newMsgs = [...msgs];
        newMsgs[newMsgs.length - 1] = { ...newMsgs[newMsgs.length - 1], content: fullAssistantMessage };

        // Finalize the real-id bucket if we got a handoff; otherwise leave
        // the optimistic bucket as the canonical store. We only mirror into
        // the optimistic bucket DURING the stream to avoid blanking the UI
        // during the URL change; once the stream ends, the real bucket owns
        // the conversation and the optimistic key can be discarded.
        if (realDbId !== null) {
            const { [optimisticId]: _opt, ...rest } = prev;
            return { ...rest, [realDbId]: newMsgs };
        }
        return { ...prev, [optimisticId]: newMsgs };
      });

      setStreamingContent(prev => {
        const { [optimisticId]: _optRemoved, ...rest1 } = prev;
        if (realDbId !== null) {
            const { [realDbId]: _dbRemoved, ...rest2 } = rest1;
            return rest2;
        }
        return rest1;
      });

      streamingSessionIdsRef.current.delete(optimisticId);
      if (realDbId !== null) streamingSessionIdsRef.current.delete(realDbId);
      window.dispatchEvent(new Event("chatCreated"));
    }
    return optimisticId;
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