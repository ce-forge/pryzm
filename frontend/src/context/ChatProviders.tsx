"use client";

import React from "react";
import { WorkspaceProvider } from "@/context/WorkspaceContext";
import { SessionProvider } from "@/context/SessionContext";
import { InferenceProvider } from "@/context/InferenceContext";
import { UploaderProvider } from "@/context/UploaderContext";
import { TestSuiteProvider } from "@/context/TestSuiteContext";

/**
 * Data-fetching providers for the chat shell. Mounted from inside AppShell
 * only after auth resolves; this prevents their first fetch from racing
 * the cookie set on login.
 */
export function ChatProviders({ children }: { children: React.ReactNode }) {
  return (
    <WorkspaceProvider>
      <SessionProvider>
        <InferenceProvider>
          <UploaderProvider>
            <TestSuiteProvider>{children}</TestSuiteProvider>
          </UploaderProvider>
        </InferenceProvider>
      </SessionProvider>
    </WorkspaceProvider>
  );
}
