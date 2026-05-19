import { useCallback, useRef, useState } from "react";
import { Message, ReferencedFile, ToolCall } from "@/types/chat";
import { apiFetch } from "@/utils/apiClient";
import { newOptimisticSessionId, newTempMessageId } from "@/utils/ids";
import type { useSessionContext } from "@/context/SessionContext";

type SessionApi = ReturnType<typeof useSessionContext>;

export interface InferenceApi {
  isProcessing: boolean;
  streamingContent: Record<string, string>;
  /**
   * Per-session live reasoning_content from reasoning-aware chat models
   * (Gemma 4 thinking mode etc.). Populated incrementally during stream;
   * cleared at the end of the turn — the finished message reads its
   * frozen reasoning from the persisted Message row.
   */
  streamingReasoning: Record<string, string>;
  /**
   * Per-session flag set by the backend's `route` SSE event right after
   * the router picks. `true` means the routed model carries the
   * `reasoning` catalog tag and the ProcessingAnimation should render
   * `Thinking…` instead of the themed phrase pool. Cleared at end-of-turn.
   */
  streamingIsReasoning: Record<string, boolean>;
  streamingToolCalls: Record<string, ToolCall[]>;
  sendMessage: (
    text: string,
    activeSessionId: string | null,
    attachments?: string[],
    skipUserAdd?: boolean,
    modes?: string[],
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
  const [streamingReasoning, setStreamingReasoning] = useState<Record<string, string>>({});
  const [streamingIsReasoning, setStreamingIsReasoning] = useState<Record<string, boolean>>({});
  const [streamingToolCalls, setStreamingToolCalls] = useState<Record<string, ToolCall[]>>({});

  // Mirror isProcessing into a ref so sendMessage can early-return on a
  // rapid second call. The state value is stale inside the useCallback
  // closure (dep array intentionally excludes isProcessing), so we guard
  // off the ref.
  const isProcessingRef = useRef(false);
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
      attachments: string[] = [],
      skipUserAdd: boolean = false,
      modes: string[] = [],
    ): Promise<string> => {
      if (isProcessingRef.current) {
        return activeSessionId || "";
      }
      isProcessingRef.current = true;
      setIsProcessing(true);

      const optimisticId = activeSessionId || newOptimisticSessionId();
      let realDbId: string | null = null;
      const ws = workspaceSlug;

      // Mark streaming BEFORE we touch the cache. The post-stream
      // loadSessionData(true) for the prior turn races with this turn's setup;
      // its DB-fetched snapshot will overwrite the cache (and lose the
      // optimistic bubbles we're about to append) unless this ref shows the
      // session is mid-stream by the time loadSessionData commits.
      sessionApi.streamingSessionIdsRef.current.add(optimisticId);

      setStreamingContent((prev) => ({ ...prev, [optimisticId]: "" }));
      setStreamingReasoning((prev) => ({ ...prev, [optimisticId]: "" }));
      setStreamingIsReasoning((prev) => ({ ...prev, [optimisticId]: false }));

      let fullAssistantMessage = "";
      let fullReasoning = "";
      let reasoningDurationS: number | null = null;
      let referencedFiles: ReferencedFile[] | undefined;
      const pendingToolCalls: ToolCall[] = [];
      let pendingUserMessageId: string | null = null;
      let pendingAssistantMessageId: string | null = null;

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

      // For a brand-new chat, immediately bind the URL to the optimistic id
      // so the cache bucket the UI reads (keyed by the URL's session id)
      // matches the bucket we just appended into. Without this, the user
      // bubble lives in messageCache[ws:optimisticId] but the UI is looking
      // at messageCache[ws:temp_new_chat], so the send appears to no-op until
      // the SSE handoff arrives — and a follow-up send before the handoff
      // would create a second session.
      if (!activeSessionId) {
        sessionApi.navigateToSession(optimisticId);
      }

      const controller = new AbortController();
      abortControllersRef.current.set(optimisticId, controller);
      // (streaming flag set near the top of sendMessage; nothing to do here)

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
              modes,
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

                // Backend now sends user_message_id alongside the started event
                // when skip_db_save=false. Stash it; we apply the swap in
                // `finally` so it lands once the bucket id is final.
                if (parsed.status === "started" && parsed.user_message_id) {
                  pendingUserMessageId = parsed.user_message_id;
                }
                if (parsed.done && parsed.assistant_message_id) {
                  pendingAssistantMessageId = parsed.assistant_message_id;
                }

                // THE HANDOFF — atomic single migrate to the backend-returned id.
                // Fires in two cases:
                //   (a) brand-new chat: optimisticId → realDbId (the normal path).
                //   (b) stale-id recovery: the URL had a session id we sent up,
                //       but the backend couldn't find it (e.g. after a DB wipe
                //       or a manual delete) and created a fresh one. The new id
                //       differs from optimisticId; migrate so subsequent sends
                //       in this turn target the real session instead of orphaning
                //       another row.
                if (
                  parsed.status === "started" &&
                  parsed.session_id &&
                  parsed.session_id !== optimisticId
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
                  setStreamingReasoning((prev) => ({
                    ...prev,
                    [newDbId]: prev[optimisticId] ?? "",
                  }));
                  setStreamingIsReasoning((prev) => ({
                    ...prev,
                    [newDbId]: prev[optimisticId] ?? false,
                  }));

                  linkSessionRef.current?.(optimisticId, newDbId);

                  // Update the URL to the real DB session id BEFORE notifying
                  // (which would otherwise trigger a loadSessionData against
                  // the stale currentSession). Subsequent sends in the same
                  // conversation rely on the URL being session-bound.
                  if (typeof window !== "undefined") {
                    const params = new URLSearchParams(window.location.search);
                    const currentUrlId = params.get("session");
                    if (!currentUrlId || currentUrlId === optimisticId) {
                      sessionApi.navigateToSession(newDbId);
                    }
                  }
                }

                if (parsed.type === "files_referenced" && parsed.files) {
                  referencedFiles = parsed.files;
                }

                if (parsed.type === "tool_call" && parsed.name) {
                  pendingToolCalls.push({
                    name: parsed.name,
                    args: parsed.args ?? {},
                    result: "",
                  });
                  setStreamingToolCalls((prev) => ({ ...prev, [optimisticId]: [...pendingToolCalls] }));
                  if (realDbId !== null) {
                    setStreamingToolCalls((prev) => ({ ...prev, [realDbId!]: [...pendingToolCalls] }));
                  }
                }

                if (parsed.type === "tool_result" && parsed.name) {
                  // Pair by ORDER (back-to-front: complete the most recent
                  // entry with empty result). Mirrors the backend pairing.
                  for (let i = pendingToolCalls.length - 1; i >= 0; i--) {
                    if (pendingToolCalls[i].result === "") {
                      pendingToolCalls[i].result = parsed.result ?? "";
                      break;
                    }
                  }
                  setStreamingToolCalls((prev) => ({ ...prev, [optimisticId]: [...pendingToolCalls] }));
                  if (realDbId !== null) {
                    setStreamingToolCalls((prev) => ({ ...prev, [realDbId!]: [...pendingToolCalls] }));
                  }
                }

                // Plain content chunks have shape {chunk: "..."} with no
                // `type` field. Typed events (reasoning_chunk, tool_call,
                // tool_result, files_referenced) also carry a `chunk` field
                // in some cases — they must NOT be folded into the content
                // accumulator, or reasoning text duplicates inside the
                // assistant message body.
                if (parsed.chunk && !parsed.type) {
                  fullAssistantMessage += parsed.chunk;
                  setStreamingContent((prev) => {
                    const next = { ...prev, [optimisticId]: fullAssistantMessage };
                    if (realDbId !== null) next[realDbId] = fullAssistantMessage;
                    return next;
                  });
                }

                if (parsed.type === "reasoning_chunk" && parsed.chunk) {
                  fullReasoning += parsed.chunk;
                  setStreamingReasoning((prev) => {
                    const next = { ...prev, [optimisticId]: fullReasoning };
                    if (realDbId !== null) next[realDbId] = fullReasoning;
                    return next;
                  });
                }

                if (parsed.type === "reasoning_done" && typeof parsed.duration_s === "number") {
                  reasoningDurationS = parsed.duration_s;
                }

                // Backend emits this right after the router picks. Sets
                // the per-session is_reasoning flag so the
                // ProcessingAnimation can show `Thinking…` from the very
                // first paint, before any reasoning chunks arrive.
                if (parsed.type === "route" && typeof parsed.is_reasoning === "boolean") {
                  setStreamingIsReasoning((prev) => {
                    const next = { ...prev, [optimisticId]: parsed.is_reasoning };
                    if (realDbId !== null) next[realDbId] = parsed.is_reasoning;
                    return next;
                  });
                }
              } catch {
                /* malformed line, skip */
              }
            }
          }
        }
      } catch {
        // AbortError, network errors — stream ended early.
      } finally {
        isProcessingRef.current = false;
        setIsProcessing(false);

        const finalKeySid = realDbId ?? optimisticId;
        sessionApi.finalizeAssistantMessage(
          ws,
          finalKeySid,
          fullAssistantMessage,
          referencedFiles,
          pendingToolCalls.length > 0 ? pendingToolCalls : undefined,
          fullReasoning || null,
          reasoningDurationS,
        );
        // Swap optimistic temp ids for the real DB UUIDs that came back in the
        // stream. No post-stream /sessions/{id} refetch = no race against the
        // next send.
        sessionApi.swapMessageIds(
          ws,
          finalKeySid,
          pendingUserMessageId,
          pendingAssistantMessageId,
        );

        setStreamingContent((prev) => {
          const next = { ...prev };
          delete next[optimisticId];
          if (realDbId !== null) delete next[realDbId];
          return next;
        });

        setStreamingReasoning((prev) => {
          const next = { ...prev };
          delete next[optimisticId];
          if (realDbId !== null) delete next[realDbId];
          return next;
        });

        setStreamingIsReasoning((prev) => {
          const next = { ...prev };
          delete next[optimisticId];
          if (realDbId !== null) delete next[realDbId];
          return next;
        });

        setStreamingToolCalls((prev) => {
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
  }, []);

  return {
    isProcessing,
    streamingContent,
    streamingReasoning,
    streamingIsReasoning,
    streamingToolCalls,
    sendMessage,
    stopInference,
    migratedIds,
    setLinkSessionCallback,
  };
}
