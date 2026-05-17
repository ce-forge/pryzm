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

  const value = useMemo(() => tester, [tester]);
  return <TestSuiteContext.Provider value={value}>{children}</TestSuiteContext.Provider>;
}

export function useTestSuiteContext(): TestSuiteApi {
  const ctx = useContext(TestSuiteContext);
  if (!ctx) throw new Error("useTestSuiteContext must be used inside <TestSuiteProvider>");
  return ctx;
}
