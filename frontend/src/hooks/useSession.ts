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
  const [isInitialLoading, setIsInitialLoading] = useState(true);

  const streamingSessionIdsRef = useRef<Set<string>>(new Set());
  const isNavigatingRef = useRef(false);

  const activeCacheKey = currentSession || "temp_new_chat";
  const messages = messageCache[activeCacheKey] || [];

  useEffect(() => {
    if (isNavigatingRef.current) {
      if (urlSessionId === currentSession) isNavigatingRef.current = false;
      return;
    }
    if (urlSessionId !== currentSession) setCurrentSession(urlSessionId);
  }, [urlSessionId, currentSession]);

  // FIX (Issue 3): Extract title fetching so we can call it on demand
  const fetchTitle = useCallback(async () => {
    if (!currentSession) return;
    try {
      const listRes = await fetch(`${APP_CONFIG.API_URL}/sessions?workspace=${workspace}`, { cache: 'no-store' });
      if (listRes.ok) {
        const sessions = await listRes.json();
        const activeSesh = sessions.find((s: any) => s.id === currentSession);
        if (activeSesh) {
          const unwanted = ["Document Upload Session", "New Diagnostic Session", "New Diagnostic Chat"];
          setSessionTitle(unwanted.includes(activeSesh.title) ? "" : activeSesh.title);
        }
      }
    } catch (e) {}
  }, [currentSession, workspace]);

  // Listen for the AI to finish its stream, then immediately grab the new title
  useEffect(() => {
    window.addEventListener("chatCreated", fetchTitle);
    return () => window.removeEventListener("chatCreated", fetchTitle);
  }, [fetchTitle]);

  useEffect(() => {
    async function loadSessionData() {
      if (!currentSession) {
        setSessionTitle("");
        setIsInitialLoading(false);
        return;
      }

      // 1. Check if this session is currently being streamed into
      const isActivelyStreaming = streamingSessionIdsRef.current.has(currentSession || "temp_new_chat");

      // 2. Only trigger the loading wipe if it's an old chat we are loading from scratch
      if (!isActivelyStreaming) {
        setIsInitialLoading(true);
      }

      // 3. Only fetch history from the DB if we don't have it AND it's not currently streaming
      if (!messageCache[currentSession] && !isActivelyStreaming) {
        try {
          const historyRes = await fetch(`${APP_CONFIG.API_URL}/sessions/${currentSession}`, { cache: 'no-store' });
          if (historyRes.ok) {
            const historyData = await historyRes.json();
            setMessageCache(prev => ({ ...prev, [currentSession]: historyData }));
          }
        } catch (error) { 
          console.error("Sync failed:", error); 
        }
      }

      // 4. Always ensure the title is up to date
      await fetchTitle();
      
      // 5. Release the loading lock
      setIsInitialLoading(false);
    }
    
    loadSessionData();
  }, [currentSession, workspace, fetchTitle]); // Added fetchTitle to deps

  const navigateToSession = useCallback((id: string) => {
    isNavigatingRef.current = true;
    setCurrentSession(id);
    router.replace(`/?workspace=${workspace}&session=${id}`, { scroll: false });
    window.dispatchEvent(new Event("chatCreated"));
  }, [workspace, router]);

  return {
    currentSession, setCurrentSession, sessionTitle, setSessionTitle,
    messages, messageCache, setMessageCache, workspace,
    isNavigatingRef, streamingSessionIdsRef, isInitialLoading,
    navigateToSession, router, urlSessionId
  };
}