import { useState, useRef, useCallback, useEffect } from "react";
import testSuiteData from "../data/test_suite.json";

const testSuitePrompts = testSuiteData as Record<string, string[]>;

export function useTestSuite(
  sendMessage: (text: string, sessionId: string | null) => Promise<string>
) {
  const [activeTestSessions, setActiveTestSessions] = useState<Set<string>>(new Set());
  const abortRefs = useRef<Record<string, boolean>>({});

  // Prevent accidental refreshes while the test suite is looping
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (activeTestSessions.size > 0) {
        e.preventDefault();
        e.returnValue = "Test suite is running. If you refresh, it will be interrupted.";
        return e.returnValue;
      }
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [activeTestSessions.size]);

  const linkSession = useCallback((oldId: string, newId: string) => {
    setActiveTestSessions(prev => {
      if (prev.has(oldId)) {
        const next = new Set(prev);
        next.add(newId);
        next.delete(oldId);
        return next;
      }
      return prev;
    });

    if (abortRefs.current[oldId] !== undefined) {
      abortRefs.current[newId] = abortRefs.current[oldId];
      delete abortRefs.current[oldId];
    }
  }, []);

  const runTestSuite = async (type: string, targetSessionId: string | null) => {
    const initialTrackingId = targetSessionId || "temp_new_chat";
    
    if (activeTestSessions.has(initialTrackingId)) return;
    
    setActiveTestSessions(prev => new Set(prev).add(initialTrackingId));
    abortRefs.current[initialTrackingId] = false;

    const prompts = testSuitePrompts[type] || [];
    let currentId = targetSessionId;

    for (const prompt of prompts) {
      const trackingId = currentId || initialTrackingId;
      if (abortRefs.current[trackingId]) break;

      const resultId = await sendMessage(prompt, currentId);
      
      if (resultId) currentId = resultId;

      const postPromptId = currentId || initialTrackingId;
      for (let i = 0; i < 30; i++) {
        if (abortRefs.current[postPromptId]) break;
        await new Promise(r => setTimeout(r, 100));
      }
    }

    setActiveTestSessions(prev => {
      const next = new Set(prev);
      next.delete(currentId || initialTrackingId);
      next.delete(initialTrackingId);
      return next;
    });
  };

  const stopTestSuite = (sessionId: string | null) => {
    const id = sessionId || "temp_new_chat";
    abortRefs.current[id] = true;
    Object.keys(abortRefs.current).forEach(key => {
        if (key.startsWith('optimistic-')) abortRefs.current[key] = true;
    });
  };

  return { activeTestSessions, runTestSuite, stopTestSuite, linkSession };
}