import { useState, useEffect, useCallback, useRef } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { APP_CONFIG } from "@/utils/constants";
import { apiFetch } from "@/utils/apiClient";
import { Message } from "@/types/chat";

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
  const isActivelyStreaming = streamingSessionIdsRef.current.has(activeRawId) ||
                               streamingSessionIdsRef.current.has("temp_new_chat");
  const isInitialLoading = !!currentSession && currentSession !== "temp_new_chat" && !hasHistory && !isActivelyStreaming;
  
  const messages = messageCache[activeCacheKey] || [];

  // Sync URL state to local state
  useEffect(() => {
    if (isNavigatingRef.current) {
      if (urlSessionId === currentSession) isNavigatingRef.current = false;
      return;
    }
    if (urlSessionId !== currentSession) setCurrentSession(urlSessionId);
  }, [urlSessionId, currentSession]);

  // The cache is read inside loadSessionData via a ref so that updates to
  // messageCache don't recreate the callback. Without this the effect that
  // depends on loadSessionData re-fires on every chunk during streaming,
  // rebinding the chatCreated listener and re-fetching sessions repeatedly.
  const messageCacheRef = useRef(messageCache);
  messageCacheRef.current = messageCache;

  // Tracks in-flight prefetch requests to avoid duplicate concurrent fetches.
  const prefetchingRef = useRef<Set<string>>(new Set());

  /**
   * Loads session history and title.
   * @param force - If true, ignores the cache and fetches fresh data from DB.
   */
  const loadSessionData = useCallback(async (force = false) => {
    if (!currentSession || currentSession.startsWith("optimistic-")) {
      setSessionTitle("");
      return;
    }

    const cacheLen = messageCacheRef.current[cacheKey(workspace, currentSession)]?.length || 0;

    // We fetch if the cache is empty OR if we are forcing a sync (after AI finishes)
    if (force || cacheLen === 0) {
      try {
        const historyRes = await apiFetch(`/sessions/${currentSession}`, { cache: 'no-store' });
        if (historyRes.ok) {
          const historyData = await historyRes.json();
          // CRITICAL: This overwrites "temp-" IDs with real DB UUIDs
          setMessageCache(prev => ({ ...prev, [cacheKey(workspace, currentSession)]: historyData }));
        }
      } catch (error) {
        console.error("History sync failed:", error);
      }
    }

    // Always refresh the title
    try {
      const listRes = await apiFetch(`/sessions?workspace=${workspace}`, { cache: 'no-store' });
      if (listRes.ok) {
        const sessions = await listRes.json();
        const activeSesh = sessions.find((s: any) => s.id === currentSession);
        if (activeSesh) {
          const unwanted = ["Document Upload Session", "New Diagnostic Session", "New Diagnostic Chat", "New Diagnostic"];
          setSessionTitle(unwanted.includes(activeSesh.title) ? "" : activeSesh.title);
        }
      }
    } catch (e) {}
  }, [currentSession, workspace, setMessageCache]);

  // Initial load. Sync after a stream completes is now triggered via the
  // SessionContext API (notifySessionCreated → loadSessionData(true)), not via
  // a window-level event bus.
  useEffect(() => {
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
  }, [setMessageCache]);

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
    loadSessionData,
  };
}