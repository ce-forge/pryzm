import { useCallback, useRef, useState } from "react";
import { Message } from "@/types/chat";
import { apiFetch } from "@/utils/apiClient";
import { newOptimisticSessionId, newTempMessageId } from "@/utils/ids";
import type { useSessionContext } from "@/context/SessionContext";

type SessionApi = ReturnType<typeof useSessionContext>;

export interface InferenceApi {
  isProcessing: boolean;
  streamingContent: Record<string, string>;
  sendMessage: (
    text: string,
    activeSessionId: string | null,
    model: string,
    attachments?: string[],
    skipUserAdd?: boolean,
  ) => Promise<string>;
  stopInference: (id?: string | null) => void;
  /**
   * Map of optimistic session id → real DB id, populated at the moment of
   * the SSE handoff. Exposed so the test runner (and stopInference) can
   * resolve a stale optimistic id into the live one.
   */
  migratedIds: React.MutableRefObject<Map<string, string>>;
  /**
   * Wire in a callback that fires synchronously the moment an optimistic→real
   * handoff happens, with (optimisticId, realId). Used by TestSuiteContext.
   */
  setLinkSessionCallback: (cb: ((oldId: string, newId: string) => void) | null) => void;
}

export function useInference(workspaceSlug: string, sessionApi: SessionApi): InferenceApi {
  const [isProcessing, setIsProcessing] = useState(false);
  const [streamingContent, setStreamingContent] = useState<Record<string, string>>({});

  const abortControllersRef = useRef<Map<string, AbortController>>(new Map());
  const migratedIds = useRef<Map<string, string>>(new Map());
  const linkSessionRef = useRef<((oldId: string, newId: string) => void) | null>(null);

  const setLinkSessionCallback = useCallback(
    (cb: ((oldId: string, newId: string) => void) | null) => {
      linkSessionRef.current = cb;
    },
    [],
  );

  const sendMessage = useCallback(
    async (
      text: string,
      activeSessionId: string | null,
      model: string,
      attachments: string[] = [],
      skipUserAdd: boolean = false,
    ): Promise<string> => {
      setIsProcessing(true);

      const optimisticId = activeSessionId || newOptimisticSessionId();
      let realDbId: string | null = null;
      const ws = workspaceSlug;

      setStreamingContent((prev) => ({ ...prev, [optimisticId]: "" }));

      let fullAssistantMessage = "";

      const startingItems: Message[] = [];
      if (!skipUserAdd) {
        startingItems.push({
          id: newTempMessageId("u"),
          role: "user",
          content: text,
          timestamp: new Date().toISOString(),
        });
      }
      startingItems.push({
        id: newTempMessageId("a"),
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
      });
      sessionApi.appendStartingMessages(ws, optimisticId, startingItems);

      const controller = new AbortController();
      abortControllersRef.current.set(optimisticId, controller);
      sessionApi.streamingSessionIdsRef.current.add(optimisticId);

      try {
        const res = await apiFetch(
          `/analyze?workspace=${encodeURIComponent(ws)}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              prompt: text,
              session_id:
                activeSessionId === "temp_new_chat" || !activeSessionId
                  ? null
                  : activeSessionId,
              attachments,
              skip_db_save: skipUserAdd,
            }),
            signal: controller.signal,
          },
        );

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
                  fullAssistantMessage = `⚠ ${parsed.error}`;
                  setStreamingContent((prev) => {
                    const next = { ...prev, [optimisticId]: fullAssistantMessage };
                    if (realDbId !== null) next[realDbId] = fullAssistantMessage;
                    return next;
                  });
                  break streamLoop;
                }

                // THE HANDOFF — atomic single migrate from optimistic → real id.
                if (
                  parsed.status === "started" &&
                  parsed.session_id &&
                  !activeSessionId
                ) {
                  const newDbId = parsed.session_id as string;
                  realDbId = newDbId;

                  sessionApi.migrateBucket(ws, optimisticId, newDbId);

                  const ctrl = abortControllersRef.current.get(optimisticId);
                  if (ctrl) abortControllersRef.current.set(newDbId, ctrl);

                  migratedIds.current.set(optimisticId, newDbId);
                  sessionApi.streamingSessionIdsRef.current.add(newDbId);

                  setStreamingContent((prev) => ({
                    ...prev,
                    [newDbId]: prev[optimisticId] ?? "",
                  }));

                  linkSessionRef.current?.(optimisticId, newDbId);
                  sessionApi.notifySessionCreated(optimisticId, newDbId);
                }

                if (parsed.chunk) {
                  fullAssistantMessage += parsed.chunk;
                  setStreamingContent((prev) => {
                    const next = { ...prev, [optimisticId]: fullAssistantMessage };
                    if (realDbId !== null) next[realDbId] = fullAssistantMessage;
                    return next;
                  });
                }
              } catch (e) {
                /* malformed line, skip */
              }
            }
          }
        }
      } catch (error: any) {
        // AbortError, network errors — stream ended early.
      } finally {
        setIsProcessing(false);

        const finalKeySid = realDbId ?? optimisticId;
        sessionApi.finalizeAssistantMessage(ws, finalKeySid, fullAssistantMessage);

        setStreamingContent((prev) => {
          const next = { ...prev };
          delete next[optimisticId];
          if (realDbId !== null) delete next[realDbId];
          return next;
        });

        sessionApi.streamingSessionIdsRef.current.delete(optimisticId);
        if (realDbId !== null) sessionApi.streamingSessionIdsRef.current.delete(realDbId);

        abortControllersRef.current.delete(optimisticId);
        if (realDbId !== null) abortControllersRef.current.delete(realDbId);

        sessionApi.notifySessionCreated(optimisticId, finalKeySid);
      }

      return optimisticId;
    },
    [workspaceSlug, sessionApi],
  );

  const stopInference = useCallback((id?: string | null) => {
    const target = id || "temp_new_chat";
    const directController = abortControllersRef.current.get(target);
    if (directController) {
      directController.abort();
      return;
    }
    const mapped = migratedIds.current.get(target);
    if (mapped) {
      const c = abortControllersRef.current.get(mapped);
      c?.abort();
      return;
    }
    for (const [key, controller] of abortControllersRef.current.entries()) {
      if (key.startsWith("optimistic-")) controller.abort();
    }
  }, []);

  return {
    isProcessing,
    streamingContent,
    sendMessage,
    stopInference,
    migratedIds,
    setLinkSessionCallback,
  };
}
