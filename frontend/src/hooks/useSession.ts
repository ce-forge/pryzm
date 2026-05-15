import { useState, useEffect, useCallback, useRef } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { APP_CONFIG } from "@/utils/constants";
import { apiFetch } from "@/utils/apiClient";
import { Message, ReferencedFile } from "@/types/chat";

// Cache key = workspace_slug:sessionId so switching workspaces doesn't bleed
// cached history across different workspace contexts.
const cacheKey = (workspaceSlug: string, sessionId: string): string =>
  `${workspaceSlug}:${sessionId}`;

export function useSession() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const urlSessionId = searchParams.get("session");
  const workspace = searchParams.get("workspace") || APP_CONFIG.DEFAULT_WORKSPACE;

  const [currentSession, setCurrentSession] = useState<string | null>(urlSessionId);
  const [sessionTitle, setSessionTitle] = useState("");
  const [messageCache, setMessageCache] = useState<Record<string, Message[]>>({});

  const streamingSessionIdsRef = useRef<Set<string>>(new Set());
  const isNavigatingRef = useRef(false);

  // Computed state for the UI
  const activeCacheKey = cacheKey(workspace, currentSession || "temp_new_chat");
  const hasHistory = (messageCache[activeCacheKey]?.length || 0) > 0;
  // streamingSessionIdsRef is keyed by raw session ids (not workspace-prefixed),
  // so check the raw session id here, not activeCacheKey.
  const activeRawId = currentSession || "temp_new_chat";
  // Ref reads during render are intentional: streaming-state changes must NOT
  // cause cascading re-renders during chat (every SSE chunk would otherwise
  // re-render the whole tree). The derived boolean is read from whatever
  // ref value existed at the start of this render — that's the design.
  // eslint-disable-next-line react-hooks/refs
  const isActivelyStreaming = streamingSessionIdsRef.current.has(activeRawId) ||
                               // eslint-disable-next-line react-hooks/refs
                               streamingSessionIdsRef.current.has("temp_new_chat");
  const isInitialLoading = !!currentSession && currentSession !== "temp_new_chat" && !hasHistory && !isActivelyStreaming;
  
  const messages = messageCache[activeCacheKey] || [];

  // Sync URL state to local state. setState-in-effect is the right pattern
  // here: URL is the source of truth for back/forward navigation, local
  // state is the source of truth for instant updates from navigateToSession.
  // The isNavigatingRef gate prevents the effect from fighting navigateToSession
  // mid-transition.
  useEffect(() => {
    if (isNavigatingRef.current) {
      if (urlSessionId === currentSession) isNavigatingRef.current = false;
      return;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (urlSessionId !== currentSession) setCurrentSession(urlSessionId);
  }, [urlSessionId, currentSession]);

  // The cache is read inside loadSessionData via a ref so that updates to
  // messageCache don't recreate the callback. Without this the effect that
  // depends on loadSessionData re-fires on every chunk during streaming,
  // rebinding the chatCreated listener and re-fetching sessions repeatedly.
  // The "ref mirrors state" pattern in the render body is React's documented
  // escape hatch for callbacks that need fresh state without re-binding deps.
  const messageCacheRef = useRef(messageCache);
  // eslint-disable-next-line react-hooks/refs
  messageCacheRef.current = messageCache;

  // Tracks in-flight prefetch requests to avoid duplicate concurrent fetches.
  const prefetchingRef = useRef<Set<string>>(new Set());

  /**
   * Title-only refresh. Used by SessionContext.notifySessionCreated after a
   * stream completes, replacing the old `loadSessionData(true)` which also
   * refetched the message list — that refetch was the source of the
   * rapid-sends cache-clobber race. Real message IDs now arrive in the SSE
   * stream itself, so there's no longer any need to re-read history from DB.
   */
  // eslint-disable-next-line react-hooks/preserve-manual-memoization -- React Compiler infers extra deps (setSessionTitle is a stable setter; included via the rule that all setters are non-deps). The manual memo here is what keeps loadSessionData stable across streaming-chunk re-renders.
  const refreshSessionMeta = useCallback(async () => {
    if (!currentSession || currentSession.startsWith("optimistic-")) {
      setSessionTitle("");
      return;
    }
    try {
      const listRes = await apiFetch(`/sessions?workspace=${workspace}`, { cache: 'no-store' });
      if (listRes.ok) {
        const sessions = await listRes.json();
        const activeSesh = sessions.find((s: { id: string; title: string }) => s.id === currentSession);
        if (activeSesh) {
          const unwanted = ["Document Upload Session", "New Diagnostic Session", "New Diagnostic Chat", "New Diagnostic"];
          setSessionTitle(unwanted.includes(activeSesh.title) ? "" : activeSesh.title);
        }
      }
    } catch {}
  }, [currentSession, workspace]);

  /**
   * Loads session history for the currently-active session if not cached.
   * Called on session navigation (the initial load). The `force` parameter
   * exists for legacy callers but no longer triggers post-stream refetches —
   * those now happen inline via the SSE-driven id-swap pathway.
   */
  // eslint-disable-next-line react-hooks/preserve-manual-memoization -- as above; manual memo holds loadSessionData stable through stream chunks
  const loadSessionData = useCallback(async (force = false) => {
    if (!currentSession || currentSession.startsWith("optimistic-")) {
      setSessionTitle("");
      return;
    }

    const cacheLen = messageCacheRef.current[cacheKey(workspace, currentSession)]?.length || 0;
    if (force || cacheLen === 0) {
      try {
        const historyRes = await apiFetch(`/sessions/${currentSession}`, { cache: 'no-store' });
        if (historyRes.ok) {
          const historyData = await historyRes.json();
          // Server returns snake_case `referenced_files`; the client
          // Message type uses camelCase. Map at the boundary so the
          // rest of the app stays in one naming convention.
          const mapped: Message[] = historyData.map((m: Message & { referenced_files?: ReferencedFile[] }) => ({
            id: m.id,
            role: m.role,
            content: m.content,
            timestamp: m.timestamp,
            referencedFiles: m.referenced_files ?? undefined,
          }));
          // Skip the overwrite if this session is mid-stream — the SSE-driven
          // path is now responsible for the optimistic→real id swap and the
          // DB snapshot would be stale relative to the in-flight optimistic
          // bubble.
          if (!streamingSessionIdsRef.current.has(currentSession)) {
            setMessageCache(prev => ({ ...prev, [cacheKey(workspace, currentSession)]: mapped }));
          }
        }
      } catch (error) {
        console.error("History sync failed:", error);
      }
    }

    await refreshSessionMeta();
  }, [currentSession, workspace, setMessageCache, refreshSessionMeta]);

  // Initial load. Sync after a stream completes is now triggered via the
  // SessionContext API (notifySessionCreated → loadSessionData(true)), not via
  // a window-level event bus.
  // Fetch on session/workspace change. loadSessionData itself does the
  // cache check so this is a no-op when chunks-already-cached. The
  // "fetch on dependency change" effect is the canonical React pattern;
  // the lint rule fires because the loaded data flows into setState
  // inside loadSessionData.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadSessionData();
  }, [currentSession, workspace, loadSessionData]);

  /**
   * Side-effect-free cache warm-up called on session row hover.
   * Does nothing if the session is already cached, already being fetched,
   * or the id is falsy / "temp_new_chat".
   */
  const prefetchSession = useCallback(async (id: string): Promise<void> => {
    if (!id || id === "temp_new_chat" || id.startsWith("optimistic-")) return;
    if (messageCacheRef.current[cacheKey(workspace, id)]?.length) return;  // already cached
    if (prefetchingRef.current.has(id)) return;           // already in-flight

    prefetchingRef.current.add(id);
    try {
      const res = await apiFetch(`/sessions/${id}`, { cache: 'no-store' });
      if (res.ok) {
        const data = await res.json();
        setMessageCache(prev => ({ ...prev, [cacheKey(workspace, id)]: data }));
      }
    } catch {
      // Prefetch is best-effort; swallow errors silently.
    } finally {
      prefetchingRef.current.delete(id);
    }
  }, [workspace, setMessageCache]);

  // eslint-disable-next-line react-hooks/preserve-manual-memoization -- as above
  const navigateToSession = useCallback((id: string) => {
    isNavigatingRef.current = true;
    setCurrentSession(id);
    router.replace(`/?workspace=${workspace}&session=${id}`, { scroll: false });
  }, [workspace, router]);

  return {
    currentSession, setCurrentSession, sessionTitle, setSessionTitle,
    messages, messageCache, setMessageCache, workspace,
    activeCacheKey,
    isNavigatingRef, streamingSessionIdsRef, isInitialLoading,
    navigateToSession, prefetchSession, router, urlSessionId,
    loadSessionData, refreshSessionMeta,
  };
}