import { useState, useEffect, useCallback, useRef } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { APP_CONFIG } from "@/utils/constants";
import { Message } from "@/types/chat";

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
  const activeCacheKey = currentSession || "temp_new_chat";
  const hasHistory = (messageCache[activeCacheKey]?.length || 0) > 0;
  const isActivelyStreaming = streamingSessionIdsRef.current.has(activeCacheKey) || 
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

  /**
   * Loads session history and title.
   * @param force - If true, ignores the cache and fetches fresh data from DB.
   */
  const loadSessionData = useCallback(async (force = false) => {
    if (!currentSession || currentSession.startsWith("optimistic-")) {
      setSessionTitle("");
      return;
    }

    const cacheLen = messageCacheRef.current[currentSession]?.length || 0;

    // We fetch if the cache is empty OR if we are forcing a sync (after AI finishes)
    if (force || cacheLen === 0) {
      try {
        const historyRes = await fetch(`${APP_CONFIG.API_URL}/sessions/${currentSession}`, { cache: 'no-store' });
        if (historyRes.ok) {
          const historyData = await historyRes.json();
          // CRITICAL: This overwrites "temp-" IDs with real DB UUIDs
          setMessageCache(prev => ({ ...prev, [currentSession]: historyData }));
        }
      } catch (error) {
        console.error("History sync failed:", error);
      }
    }

    // Always refresh the title
    try {
      const listRes = await fetch(`${APP_CONFIG.API_URL}/sessions?workspace=${workspace}`, { cache: 'no-store' });
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

  // Initial Load & Event Listener for Sync
  useEffect(() => {
    loadSessionData();

    // The 'chatCreated' event is dispatched by useInference.ts when a stream ends.
    const handleSync = () => loadSessionData(true);
    window.addEventListener("chatCreated", handleSync);
    
    return () => window.removeEventListener("chatCreated", handleSync);
  }, [currentSession, workspace, loadSessionData]);

  const navigateToSession = useCallback((id: string) => {
    isNavigatingRef.current = true;
    setCurrentSession(id);
    router.replace(`/?workspace=${workspace}&session=${id}`, { scroll: false });
    // Trigger a refresh of the sidebar list
    window.dispatchEvent(new Event("chatCreated"));
  }, [workspace, router]);

  return {
    currentSession, setCurrentSession, sessionTitle, setSessionTitle,
    messages, messageCache, setMessageCache, workspace,
    isNavigatingRef, streamingSessionIdsRef, isInitialLoading,
    navigateToSession, router, urlSessionId
  };
}