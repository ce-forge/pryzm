"use client";

import React, { createContext, useContext, useEffect, useMemo } from "react";
import { useTestSuite } from "@/hooks/useTestSuite";
import { useInferenceContext } from "@/context/InferenceContext";

type TestSuiteApi = ReturnType<typeof useTestSuite>;

const TestSuiteContext = createContext<TestSuiteApi | null>(null);

export function TestSuiteProvider({ children }: { children: React.ReactNode }) {
  const inference = useInferenceContext();
  const tester = useTestSuite((text, sId) => inference.sendMessage(text, sId));

  // Wire the runner's linkSession into Inference so it's notified
  // synchronously when an optimistic→real id handoff happens.
  useEffect(() => {
    inference.setLinkSessionCallback(tester.linkSession);
    return () => inference.setLinkSessionCallback(null);
  }, [inference, tester.linkSession]);

  // Memoise on the hook's output keys, not on the wrapper object itself —
  // useTestSuite returns a fresh object every render, so a `[tester]` dep
  // would trip on every parent render. `runTestSuite` and `stopTestSuite`
  // are inline-recreated by the hook today; this memo recomputes when
  // they do, which is correct (and as good as we can get without
  // restructuring useTestSuite — F6's scope is provider-level).
  // exhaustive-deps would suggest `tester` — the wrapper that recreates
  // every render, which is what we're trying to dodge.
  const value = useMemo(
    () => tester,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tester.activeTestSessions, tester.runTestSuite, tester.stopTestSuite, tester.linkSession],
  );
  return <TestSuiteContext.Provider value={value}>{children}</TestSuiteContext.Provider>;
}

export function useTestSuiteContext(): TestSuiteApi {
  const ctx = useContext(TestSuiteContext);
  if (!ctx) throw new Error("useTestSuiteContext must be used inside <TestSuiteProvider>");
  return ctx;
}
