import { useState, useRef } from "react";
import testSuiteData from "../data/test_suite.json";

const testSuitePrompts = testSuiteData as Record<string, string[]>;

export function useTestSuite(
  sendMessage: (text: string, sessionId: string | null) => Promise<string | null | undefined>
) {
  const [activeTestSessions, setActiveTestSessions] = useState<Set<string>>(new Set());
  const abortRefs = useRef<Record<string, boolean>>({});

  const linkSession = (oldId: string, newId: string) => {
    setActiveTestSessions(prev => {
      if (prev.has(oldId)) {
        const next = new Set(prev);
        next.delete(oldId);
        next.add(newId);
        return next;
      }
      return prev;
    });
    if (abortRefs.current[oldId] !== undefined) {
      abortRefs.current[newId] = abortRefs.current[oldId];
    }
  };

  const runTestSuite = async (type: string, targetSessionId: string | null) => {
    const initialId = targetSessionId || "temp_new_chat";
    if (activeTestSessions.has(initialId)) return;
    
    setActiveTestSessions(prev => new Set(prev).add(initialId));
    abortRefs.current[initialId] = false;

    const prompts = testSuitePrompts[type] || [];
    let currentId = targetSessionId;

    for (const prompt of prompts) {
      const trackingId = currentId || initialId;
      if (abortRefs.current[trackingId]) break;

      const resultId = await sendMessage(prompt, currentId);
      if (resultId) currentId = resultId;

      const finalTrackingId = currentId || initialId;
      for (let i = 0; i < 30; i++) {
        if (abortRefs.current[finalTrackingId]) break;
        await new Promise(r => setTimeout(r, 100));
      }
    }

    setActiveTestSessions(prev => {
      const next = new Set(prev);
      next.delete(currentId || initialId);
      return next;
    });
  };

  const stopTestSuite = (sessionId: string | null) => {
    const id = sessionId || "temp_new_chat";
    abortRefs.current[id] = true;
  };

  return { activeTestSessions, runTestSuite, stopTestSuite, linkSession };
}