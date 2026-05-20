import { useCallback, useRef, useState } from "react";
import { Message, ReferencedFile, ToolCall } from "@/types/chat";
import { apiFetch } from "@/utils/apiClient";
import { newOptimisticSessionId, newTempMessageId } from "@/utils/ids";
import type { useSessionContext } from "@/context/SessionContext";

type SessionApi = ReturnType<typeof useSessionContext>;

/**
 * Typed events parsed from the backend's NDJSON SSE stream. Each line
 * arrives as a JSON object; `parseSseLine` is a pure mapper that turns
 * those objects into one of these discriminated variants. Anything the
 * stream loop doesn't act on returns `null` and is skipped.
 */
type StreamEvent =
  | { kind: "started"; sessionId: string; userMessageId: string | null }
  | { kind: "route"; isReasoning: boolean }
  | { kind: "chunk"; content: string }
  | { kind: "reasoning_chunk"; content: string }
  | { kind: "reasoning_done"; durationS: number }
  | { kind: "tool_call"; name: string; args: Record<string, unknown> }
  | { kind: "tool_result"; result: string }
  | { kind: "files_referenced"; files: ReferencedFile[] }
  | { kind: "done"; assistantMessageId: string | null }
  | { kind: "error"; message: string };

function parseSseLine(parsed: unknown): StreamEvent | null {
  if (!parsed || typeof parsed !== "object") return null;
  const p = parsed as Record<string, unknown>;

  if (typeof p.error === "string") {
    return { kind: "error", message: p.error };
  }

  if (p.status === "started" && typeof p.session_id === "string") {
    return {
      kind: "started",
      sessionId: p.session_id,
      userMessageId: typeof p.user_message_id === "string" ? p.user_message_id : null,
    };
  }

  if (p.done === true) {
    return {
      kind: "done",
      assistantMessageId: typeof p.assistant_message_id === "string" ? p.assistant_message_id : null,
    };
  }

  if (p.type === "route" && typeof p.is_reasoning === "boolean") {
    return { kind: "route", isReasoning: p.is_reasoning };
  }

  if (p.type === "files_referenced" && Array.isArray(p.files)) {
    return { kind: "files_referenced", files: p.files as ReferencedFile[] };
  }

  if (p.type === "tool_call" && typeof p.name === "string") {
    return {
      kind: "tool_call",
      name: p.name,
      args: (p.args as Record<string, unknown>) ?? {},
    };
  }

  if (p.type === "tool_result") {
    return { kind: "tool_result", result: typeof p.result === "string" ? p.result : "" };
  }

  if (p.type === "reasoning_chunk" && typeof p.chunk === "string") {
    return { kind: "reasoning_chunk", content: p.chunk };
  }

  if (p.type === "reasoning_done" && typeof p.duration_s === "number") {
    return { kind: "reasoning_done", durationS: p.duration_s };
  }

  // Plain content chunks have shape {chunk: "..."} with no `type` field.
  // Typed events sometimes also carry a `chunk` field — those are handled
  // above and must not fall through here, or reasoning text duplicates
  // into the assistant content accumulator.
  if (typeof p.chunk === "string" && p.type === undefined) {
    return { kind: "chunk", content: p.chunk };
  }

  return null;
}

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
  /**
   * Per-session reasoning duration captured the moment the backend's
   * `reasoning_done` event lands — fires BEFORE content streams. This
   * is what the ThinkingPanel uses to flip from `Thinking…` (active) to
   * `Thought for X.Xs` (done) without waiting for the whole turn to
   * finish.  Null until reasoning_done arrives.
   */
  streamingReasoningDurationS: Record<string, number | null>;
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
  const [streamingReasoningDurationS, setStreamingReasoningDurationS] = useState<Record<string, number | null>>({});
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

  // Walk the five streaming maps and copy the optimistic-keyed entry to
  // the real-id key, then drop the optimistic key. Called once per send,
  // the instant the backend hands back the real session id. Maps that
  // weren't yet written for this send (e.g. tool-call map before any
  // tool fires) skip via the `in` check.
  const migrateStreamingMaps = useCallback((fromKey: string, toKey: string) => {
    const migrate = <V,>(prev: Record<string, V>): Record<string, V> => {
      if (!(fromKey in prev)) return prev;
      const next = { ...prev, [toKey]: prev[fromKey] };
      delete next[fromKey];
      return next;
    };
    setStreamingContent(migrate);
    setStreamingReasoning(migrate);
    setStreamingIsReasoning(migrate);
    setStreamingReasoningDurationS(migrate);
    setStreamingToolCalls(migrate);
  }, []);

  const clearStreamingForSession = useCallback((sessionKey: string) => {
    const drop = <V,>(prev: Record<string, V>): Record<string, V> => {
      const next = { ...prev };
      delete next[sessionKey];
      return next;
    };
    setStreamingContent(drop);
    setStreamingReasoning(drop);
    setStreamingIsReasoning(drop);
    setStreamingReasoningDurationS(drop);
    setStreamingToolCalls(drop);
  }, []);

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
      // Single key every streaming-map write targets for this send. Starts
      // as the optimistic id; flips to the real DB id atomically inside
      // the `started` handler once the backend hands one back.
      let liveKey = optimisticId;
      const ws = workspaceSlug;

      // Mark streaming BEFORE we touch the cache. The post-stream
      // loadSessionData(true) for the prior turn races with this turn's setup;
      // its DB-fetched snapshot will overwrite the cache (and lose the
      // optimistic bubbles we're about to append) unless this ref shows the
      // session is mid-stream by the time loadSessionData commits.
      sessionApi.streamingSessionIdsRef.current.add(optimisticId);

      setStreamingContent((prev) => ({ ...prev, [liveKey]: "" }));
      setStreamingReasoning((prev) => ({ ...prev, [liveKey]: "" }));
      setStreamingIsReasoning((prev) => ({ ...prev, [liveKey]: false }));
      setStreamingReasoningDurationS((prev) => ({ ...prev, [liveKey]: null }));

      let fullAssistantMessage = "";
      let fullReasoning = "";
      let reasoningDurationS: number | null = null;
      let referencedFiles: ReferencedFile[] | undefined;
      const pendingToolCalls: ToolCall[] = [];
      // Index of the next unfilled tool_call awaiting a tool_result.
      // The previous implementation walked pendingToolCalls backwards
      // looking for result === "" — which mispairs whenever a tool
      // legitimately returns the empty string. Backend emits one
      // tool_result per tool_call in order, so a monotonic counter is
      // the right primitive.
      let nextToolResultIdx = 0;
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
              let parsed: unknown;
              try {
                parsed = JSON.parse(line);
              } catch {
                continue;
              }
              const event = parseSseLine(parsed);
              if (!event) continue;

              switch (event.kind) {
                case "error": {
                  fullAssistantMessage = `⚠ ${event.message}`;
                  setStreamingContent((prev) => ({ ...prev, [liveKey]: fullAssistantMessage }));
                  break streamLoop;
                }

                case "started": {
                  if (event.userMessageId) pendingUserMessageId = event.userMessageId;

                  // THE HANDOFF — atomic single migrate to the backend-returned id.
                  // Fires in two cases:
                  //   (a) brand-new chat: optimisticId → realDbId (the normal path).
                  //   (b) stale-id recovery: the URL had a session id we sent up,
                  //       but the backend couldn't find it (e.g. after a DB wipe
                  //       or a manual delete) and created a fresh one. The new id
                  //       differs from optimisticId; migrate so subsequent sends
                  //       in this turn target the real session instead of orphaning
                  //       another row.
                  if (event.sessionId !== optimisticId) {
                    const newDbId = event.sessionId;
                    realDbId = newDbId;

                    sessionApi.migrateBucket(ws, optimisticId, newDbId);

                    const ctrl = abortControllersRef.current.get(optimisticId);
                    if (ctrl) abortControllersRef.current.set(newDbId, ctrl);

                    migratedIds.current.set(optimisticId, newDbId);
                    sessionApi.streamingSessionIdsRef.current.add(newDbId);

                    migrateStreamingMaps(optimisticId, newDbId);
                    liveKey = newDbId;

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
                  break;
                }

                case "done": {
                  if (event.assistantMessageId) pendingAssistantMessageId = event.assistantMessageId;
                  break;
                }

                case "route": {
                  const flag = event.isReasoning;
                  setStreamingIsReasoning((prev) => ({ ...prev, [liveKey]: flag }));
                  break;
                }

                case "files_referenced": {
                  referencedFiles = event.files;
                  break;
                }

                case "tool_call": {
                  pendingToolCalls.push({
                    name: event.name,
                    args: event.args,
                    result: "",
                  });
                  setStreamingToolCalls((prev) => ({ ...prev, [liveKey]: [...pendingToolCalls] }));
                  break;
                }

                case "tool_result": {
                  // Pair by ORDER via a monotonic counter so empty-string
                  // results don't poison the lookup.
                  if (nextToolResultIdx < pendingToolCalls.length) {
                    pendingToolCalls[nextToolResultIdx].result = event.result;
                    nextToolResultIdx += 1;
                  }
                  setStreamingToolCalls((prev) => ({ ...prev, [liveKey]: [...pendingToolCalls] }));
                  break;
                }

                case "chunk": {
                  fullAssistantMessage += event.content;
                  setStreamingContent((prev) => ({ ...prev, [liveKey]: fullAssistantMessage }));
                  break;
                }

                case "reasoning_chunk": {
                  fullReasoning += event.content;
                  setStreamingReasoning((prev) => ({ ...prev, [liveKey]: fullReasoning }));
                  break;
                }

                case "reasoning_done": {
                  reasoningDurationS = event.durationS;
                  const d = event.durationS;
                  setStreamingReasoningDurationS((prev) => ({ ...prev, [liveKey]: d }));
                  break;
                }
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

        clearStreamingForSession(liveKey);

        sessionApi.streamingSessionIdsRef.current.delete(optimisticId);
        if (realDbId !== null) sessionApi.streamingSessionIdsRef.current.delete(realDbId);

        abortControllersRef.current.delete(optimisticId);
        if (realDbId !== null) abortControllersRef.current.delete(realDbId);

        sessionApi.notifySessionCreated(optimisticId, finalKeySid);
      }

      return optimisticId;
    },
    [workspaceSlug, sessionApi, migrateStreamingMaps, clearStreamingForSession],
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
    streamingReasoningDurationS,
    streamingToolCalls,
    sendMessage,
    stopInference,
    migratedIds,
    setLinkSessionCallback,
  };
}
