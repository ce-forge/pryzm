"use client";

import React, { createContext, useContext } from "react";
import { useUploader } from "@/hooks/useUploader";
import { useSessionContext } from "@/context/SessionContext";

type UploaderApi = ReturnType<typeof useUploader>;

const UploaderContext = createContext<UploaderApi | null>(null);

export function UploaderProvider({ children }: { children: React.ReactNode }) {
  const { workspace } = useSessionContext();
  const uploader = useUploader(workspace);
  return <UploaderContext.Provider value={uploader}>{children}</UploaderContext.Provider>;
}

export function useUploaderContext(): UploaderApi {
  const ctx = useContext(UploaderContext);
  if (!ctx) throw new Error("useUploaderContext must be used inside <UploaderProvider>");
  return ctx;
}
