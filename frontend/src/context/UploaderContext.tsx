"use client";

import React, { createContext, useContext, useMemo } from "react";
import { useUploader } from "@/hooks/useUploader";
import { useSessionMetaContext } from "@/context/SessionMetaContext";

type UploaderApi = ReturnType<typeof useUploader>;

const UploaderContext = createContext<UploaderApi | null>(null);

export function UploaderProvider({ children }: { children: React.ReactNode }) {
  const { workspace } = useSessionMetaContext();
  const uploader = useUploader(workspace);
  // useUploader returns a fresh object every render; memoise on its
  // output keys so consumer reference identity holds when nothing
  // observable changed. `processUploadQueue` is recreated on each
  // render today, so this memo flushes when it does — that's
  // intentional: F6 is not in the business of restructuring
  // useUploader, only of avoiding a guaranteed new context value.
  // exhaustive-deps would want `uploader` itself; that's the wrapper we
  // are explicitly trying not to depend on.
  const value = useMemo(
    () => uploader,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [uploader.uploads, uploader.setUploads, uploader.processUploadQueue, uploader.clearQueue],
  );
  return <UploaderContext.Provider value={value}>{children}</UploaderContext.Provider>;
}

export function useUploaderContext(): UploaderApi {
  const ctx = useContext(UploaderContext);
  if (!ctx) throw new Error("useUploaderContext must be used inside <UploaderProvider>");
  return ctx;
}
