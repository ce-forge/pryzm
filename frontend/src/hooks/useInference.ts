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
    const streamTargetId = activeSessionId || `optimistic-${Date.now()}`;
    setStreamingContent(prev => ({ ...prev, [streamTargetId]: "" }));

    let fullAssistantMessage = "";

    setMessageCache(prev => {
      const existing = prev[streamTargetId] || [];
      const newItems: Message[] = [];
      if (!skipUserAdd) {
        newItems.push({ id: `temp-${Date.now()}-u`, role: "user", content: text, timestamp: new Date().toISOString() });
      }
      newItems.push({ id: `temp-${Date.now()}-a`, role: "assistant", content: "", timestamp: new Date().toISOString() });
      return { ...prev, [streamTargetId]: [...existing, ...newItems] };
    });

    if (!activeSessionId) onSessionCreated("temp_new_chat", streamTargetId);

    const controller = new AbortController();
    abortControllersRef.current.set(streamTargetId, controller);
    streamingSessionIdsRef.current.add(streamTargetId);

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
              if (parsed.status === "started" && parsed.session_id && !activeSessionId) {
                onSessionCreated(streamTargetId, parsed.session_id);
              }
              if (parsed.chunk) {
                fullAssistantMessage += parsed.chunk;
                setStreamingContent(prev => ({ ...prev, [streamTargetId]: fullAssistantMessage }));
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
        const msgs = prev[streamTargetId] || [];
        if (msgs.length === 0) return prev;
        const newMsgs = [...msgs];
        newMsgs[newMsgs.length - 1] = { ...newMsgs[newMsgs.length - 1], content: fullAssistantMessage };
        return { ...prev, [streamTargetId]: newMsgs };
      });
      setStreamingContent(prev => { const n = {...prev}; delete n[streamTargetId]; return n; });
      streamingSessionIdsRef.current.delete(streamTargetId);
      window.dispatchEvent(new Event("chatCreated"));
    }
    return streamTargetId;
  }, [workspace, setMessageCache, streamingSessionIdsRef, onSessionCreated]);

  return { 
    isProcessing, 
    streamingContent, 
    sendMessage, 
    stopInference: (id?: string | null) => {
      // Muted: Allow backend delay to finish typing the string out to the UI
      console.log("Stop bypassed to allow delayed stream completion.");
    } 
  };
}