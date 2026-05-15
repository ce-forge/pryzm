import { useState, useRef, useCallback, useEffect } from "react";
import testSuiteData from "../data/test_suite.json";

const testSuitePrompts = testSuiteData as Record<string, string[]>;

export function useTestSuite(
  sendMessage: (text: string, sessionId: string | null) => Promise<string>
) {
  const [activeTestSessions, setActiveTestSessions] = useState<Set<string>>(new Set());
  const abortRefs = useRef<Record<string, boolean>>({});
  
  // NEW: A dictionary to store ID translations (optimistic -> real backend UUID)
  const idMapRef = useRef<Record<string, string>>({});

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
    // Record the translation so the loop can find it
    idMapRef.current[oldId] = newId;

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
    let trackingId = initialTrackingId;

    // Move the tracking key off "temp_new_chat" (or any prior id) onto
    // whatever session id the run is actually running against. Without
    // this, clicking "New Chat" while a test runs from a freshly-started
    // session leaves "temp_new_chat" in activeTestSessions, and the
    // new chat's input shows the stop-test button.
    const migrateTracking = (newId: string) => {
      if (!newId || newId === trackingId) return;
      setActiveTestSessions(prev => {
        const next = new Set(prev);
        next.delete(trackingId);
        next.add(newId);
        return next;
      });
      abortRefs.current[newId] = abortRefs.current[trackingId] ?? false;
      delete abortRefs.current[trackingId];
      trackingId = newId;
    };

    for (const prompt of prompts) {
      if (abortRefs.current[trackingId]) break;

      const resultId = await sendMessage(prompt, currentId);

      // resultId is the optimistic id from useInference; linkSession may
      // have already populated idMapRef with the real DB id by now.
      if (resultId) {
        const resolved = idMapRef.current[resultId] || resultId;
        migrateTracking(resolved);
        currentId = resolved;
      }

      for (let i = 0; i < 30; i++) {
        if (abortRefs.current[trackingId]) break;
        await new Promise(r => setTimeout(r, 100));
      }
    }

    setActiveTestSessions(prev => {
      const next = new Set(prev);
      next.delete(trackingId);
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