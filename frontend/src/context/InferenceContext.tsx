"use client";

import React, { createContext, useContext } from "react";
import { useInference, type InferenceApi } from "@/hooks/useInference";
import { useSessionContext } from "@/context/SessionContext";

const InferenceContext = createContext<InferenceApi | null>(null);

export function InferenceProvider({ children }: { children: React.ReactNode }) {
  const sessionApi = useSessionContext();
  const inference = useInference(sessionApi.workspace, sessionApi);
  return <InferenceContext.Provider value={inference}>{children}</InferenceContext.Provider>;
}

export function useInferenceContext(): InferenceApi {
  const ctx = useContext(InferenceContext);
  if (!ctx) throw new Error("useInferenceContext must be used inside <InferenceProvider>");
  return ctx;
}
