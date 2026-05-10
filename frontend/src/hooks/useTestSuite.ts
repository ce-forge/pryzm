import { useState, useRef, useCallback } from "react";
import testSuiteData from "../data/test_suite.json";

const testSuitePrompts = testSuiteData as Record<string, string[]>;

export function useTestSuite(
  sendMessage: (text: string, sessionId: string | null) => Promise<string>
) {
  const [activeTestSessions, setActiveTestSessions] = useState<Set<string>>(new Set());
  const abortRefs = useRef<Record<string, boolean>>({});

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
    // If starting from scratch, track under temp ID
    const initialTrackingId = targetSessionId || "temp_new_chat";
    
    if (activeTestSessions.has(initialTrackingId)) return;
    
    setActiveTestSessions(prev => new Set(prev).add(initialTrackingId));
    abortRefs.current[initialTrackingId] = false;

    const prompts = testSuitePrompts[type] || [];
    let currentId = targetSessionId;

    for (const prompt of prompts) {
      // Use currentId if we have one, otherwise initial tracking ID
      const trackingId = currentId || initialTrackingId;
      if (abortRefs.current[trackingId]) break;

      const resultId = await sendMessage(prompt, currentId);
      
      // Update local pointer if ID changed (Optimistic -> UUID)
      if (resultId) currentId = resultId;

      // Pause for visual feedback
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
    // Also check for any optimistic IDs matching this session in abortRefs
    Object.keys(abortRefs.current).forEach(key => {
        if (key.startsWith('optimistic-')) abortRefs.current[key] = true;
    });
  };

  return { activeTestSessions, runTestSuite, stopTestSuite, linkSession };
}