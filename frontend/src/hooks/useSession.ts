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

  const messages = currentSession 
    ? (messageCache[currentSession] || []) 
    : (messageCache["temp_new_chat"] || []);

  useEffect(() => {
    if (isNavigatingRef.current) {
      if (urlSessionId === currentSession) isNavigatingRef.current = false;
      return;
    }
    if (urlSessionId !== currentSession) setCurrentSession(urlSessionId);
  }, [urlSessionId, currentSession]);

  useEffect(() => {
    async function loadSessionData() {
      if (!currentSession) {
        setSessionTitle("");
        return;
      }

      if (!messageCache[currentSession] && !streamingSessionIdsRef.current.has(currentSession)) {
        try {
          const historyRes = await fetch(`${APP_CONFIG.API_URL}/sessions/${currentSession}`, { cache: 'no-store' });
          if (historyRes.ok) {
            const historyData = await historyRes.json();
            setMessageCache(prev => ({ ...prev, [currentSession]: historyData }));
          }
        } catch (error) { console.error("History sync failed:", error); }
      }

      try {
        const listRes = await fetch(`${APP_CONFIG.API_URL}/sessions?workspace=${workspace}`, { cache: 'no-store' });
        if (listRes.ok) {
          const sessions = await listRes.json();
          const activeSesh = sessions.find((s: any) => s.id === currentSession);
          if (activeSesh) setSessionTitle(activeSesh.title);
        }
      } catch (e) {}
    }
    loadSessionData();
  }, [currentSession, workspace]);

  const navigateToSession = useCallback((id: string) => {
    isNavigatingRef.current = true;
    setCurrentSession(id);
    router.replace(`/?workspace=${workspace}&session=${id}`, { scroll: false });
    window.dispatchEvent(new Event("chatCreated"));
  }, [workspace, router]);

  const isLoadingHistory = currentSession ? !messageCache[currentSession] : false;

  return {
    currentSession, setCurrentSession, sessionTitle, setSessionTitle,
    messages,
    messageCache, setMessageCache,
    workspace, isNavigatingRef, streamingSessionIdsRef,
    navigateToSession, router, urlSessionId, isLoadingHistory
  };
}