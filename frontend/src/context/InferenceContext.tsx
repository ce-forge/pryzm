"use client";

import React, { createContext, useContext, useMemo } from "react";
import { useInference, type InferenceApi } from "@/hooks/useInference";
import { useSessionContext } from "@/context/SessionContext";

const InferenceContext = createContext<InferenceApi | null>(null);

export function InferenceProvider({ children }: { children: React.ReactNode }) {
  const sessionApi = useSessionContext();
  const inference = useInference(sessionApi.workspace, sessionApi);
  // Memoise on useInference's output keys so we don't hand consumers a
  // fresh object every parent render. The streaming maps and isProcessing
  // genuinely change during a turn; the callbacks and refs are stable.
  // exhaustive-deps wants the wrapper object itself; that defeats the
  // purpose — `inference` is a new reference each render.
  const value = useMemo(
    () => inference,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      inference.isProcessing,
      inference.streamingContent,
      inference.streamingReasoning,
      inference.streamingIsReasoning,
      inference.streamingReasoningDurationS,
      inference.streamingToolCalls,
      inference.sendMessage,
      inference.stopInference,
      inference.migratedIds,
      inference.setLinkSessionCallback,
    ],
  );
  return <InferenceContext.Provider value={value}>{children}</InferenceContext.Provider>;
}

export function useInferenceContext(): InferenceApi {
  const ctx = useContext(InferenceContext);
  if (!ctx) throw new Error("useInferenceContext must be used inside <InferenceProvider>");
  return ctx;
}
